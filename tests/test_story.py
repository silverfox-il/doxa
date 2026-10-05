"""Stories: each published post is shared once as a story, best effort."""

from __future__ import annotations

from PIL import Image

from doxa import story
from doxa.instagram import Client, InstagramError
from doxa.queue import Status, content_hash, dump_post, load_post

from .test_publish import (  # noqa: F401
    SHA,
    SLUG,
    approved_post,
    gh_calls,
    publisher,
    reel_post,
)


def _story_jpg(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1920), "black").save(path.parent / "story.jpg", "JPEG")


def test_story_body_picks_image_or_video():
    assert Client.story_body("https://x/a.jpg") == {
        "media_type": "STORIES",
        "image_url": "https://x/a.jpg",
    }
    assert Client.story_body("https://x/reel.mp4")["video_url"] == "https://x/reel.mp4"


def test_regular_posts_get_no_automatic_story(repo, gh_calls):  # noqa: F811
    # Even with a story.jpg left over from before, regular posts are shared by the owner.
    path = approved_post(repo)
    _story_jpg(path)
    p, client, committer, logs = publisher(repo)
    assert p.run(dry_run=False) == 0
    assert "create_story_container" not in client.calls
    assert any("story: none" in line for line in logs)
    assert load_post(path).story_id is None


def test_series_failure_keeps_post_published(repo, gh_calls, monkeypatch):  # noqa: F811
    path = _series_post(repo, monkeypatch)
    p, client, committer, logs = publisher(
        repo, head=lambda u: (200, "video/mp4" if u.endswith(".mp4") else "image/jpeg")
    )
    client.create_reel_container = lambda url, caption: "reel-parent"
    client.fail["create_story_container"] = [InstagramError("story boom")] * 5
    assert p.run(dry_run=False) == 0
    post = load_post(path)
    assert post.status == Status.published
    assert post.story_id is None and "story boom" in post.story_error
    assert committer.commits[-1] == "publish: 2026-09-25-post story failed"


def test_dry_run_previews_series(repo, gh_calls, monkeypatch):  # noqa: F811
    _series_post(repo, monkeypatch)
    p, client, committer, logs = publisher(
        repo, head=lambda u: (200, "video/mp4" if u.endswith(".mp4") else "image/jpeg")
    )
    assert p.run(dry_run=True) == 0
    text = "\n".join(logs)
    assert text.count('"media_type": "STORIES"') == 3 and "series/2.jpg" in text
    assert committer.commits == []


def _series_post(repo, monkeypatch, stories=("שני", "שלישי")):
    path = reel_post(repo, monkeypatch)
    post = load_post(path)
    post.reel.stories = list(stories)
    post.approved_hash = content_hash(post, path.parent)
    dump_post(post, path)
    (path.parent / "series").mkdir()
    for i in range(1, len(stories) + 1):
        _story_jpg(path.parent / "series" / "x")  # writes series/story.jpg
        (path.parent / "series" / "story.jpg").rename(path.parent / "series" / f"{i}.jpg")
    return path


def test_series_files_start_with_the_reel(repo, monkeypatch):
    path = _series_post(repo, monkeypatch)
    post = load_post(path)
    assert story.story_files(post, path.parent) == ["reel.mp4", "series/1.jpg", "series/2.jpg"]


def test_series_publishes_reel_then_each_story_in_order(repo, gh_calls, monkeypatch):  # noqa: F811
    path = _series_post(repo, monkeypatch)
    urls = []

    def head(u):
        return 200, "video/mp4" if u.endswith(".mp4") else "image/jpeg"

    p, client, committer, logs = publisher(repo, head=head)
    real = client.create_story_container

    def create(u):
        urls.append(u.rsplit("/queue/2026-09-25-post/", 1)[1])
        return real(u)

    client.create_story_container = create
    client.create_reel_container = lambda url, caption: "reel-parent"
    assert p.run(dry_run=False) == 0
    assert urls == ["reel.mp4", "series/1.jpg", "series/2.jpg"]
    post = load_post(path)
    assert post.story_id == "media-1,media-1,media-1" and post.story_error is None


def test_series_stories_are_checked_by_the_rules():
    from doxa import rules
    from doxa.queue import Post

    from .conftest import render_post_data

    reel = {"lines": ["א ב ג", "ד"], "music": "a.mp3", "per_line": 4, "hold": 7,
            "stories": ["גבר שמחכה", "Zונות - כן"]}
    post = Post.model_validate(render_post_data(mode="reel", slides=[], reel=reel))
    where = [w for w, _ in rules.post_texts(post)]
    assert "story 2" in where and "story 3" in where


def test_story_count_and_length_are_limited():
    import pytest

    from doxa.queue import Reel

    base = {"lines": ["א", "ב"], "music": "a.mp3", "per_line": 4, "hold": 7}
    with pytest.raises(ValueError, match="1-3 follow-up"):
        Reel.model_validate({**base, "stories": ["א", "ב", "ג", "ד"]})
    with pytest.raises(ValueError, match="characters"):
        Reel.model_validate({**base, "stories": ["א" * 161]})


def test_story_html_has_banner_and_counter():
    last = story.series_html("ההמשך", 3, 3)
    assert story.BANNER_MORE in last and "3/3" in last
    assert story.BANNER_MORE not in story.series_html("אמצע", 2, 3)
    assert story.BANNER_REEL in story.reel_story_html("הוק")
    assert story.BANNER_POST in story.post_story_html(b"x")


def test_render_stories_series_only(tmp_path):
    import pytest

    pytest.importorskip("playwright.sync_api")
    from doxa.queue import Post

    from .conftest import render_post_data

    (tmp_path / "story.jpg").write_bytes(b"old")
    assert story.render_stories(Post.model_validate(render_post_data()), tmp_path) == []
    assert not (tmp_path / "story.jpg").exists()  # stale file removed
    reel = {"lines": ["א ב ג", "ד"], "music": "a.mp3", "per_line": 4, "hold": 7,
            "stories": ["שני", "שלישי"]}
    post = Post.model_validate(render_post_data(mode="reel", slides=[], reel=reel))
    outs = story.render_stories(post, tmp_path)
    assert [o.relative_to(tmp_path).as_posix() for o in outs] == ["series/1.jpg", "series/2.jpg"]
    with Image.open(outs[0]) as im:
        assert im.size == (1080, 1920) and im.format == "JPEG"


def test_tease_reels_allow_up_to_8_lines_plain_reels_6():
    import pytest

    from doxa.queue import Reel

    lines = ["שורה"] * 8
    Reel.model_validate({"lines": lines, "music": "a.mp3", "per_line": 1.4, "hold": 4,
                         "stories": ["שני"]})
    with pytest.raises(ValueError, match="2-6 lines"):
        Reel.model_validate({"lines": lines, "music": "a.mp3", "per_line": 1.4, "hold": 4})


def test_tease_frame_is_right_aligned_style():
    from doxa import reel

    assert "class='tease'" in reel.frame_html(["א", "ב"], 1, tease=True)
    assert "class='tease'" not in reel.frame_html(["א", "ב"], 1)


def test_boxes_reel_style():
    from doxa import reel
    from doxa.queue import Reel

    r = Reel.model_validate({"lines": ["א", "ב"], "music": "a.mp3", "per_line": 4, "hold": 7,
                             "style": "boxes"})
    assert r.style == "boxes"
    assert "class='boxes'" in reel.frame_html(r.lines, 1, look="boxes")
