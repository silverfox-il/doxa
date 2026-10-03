"""Stories: each published post is shared once as a story, best effort."""

from __future__ import annotations

from PIL import Image

from doxa import render
from doxa.instagram import Client, InstagramError
from doxa.queue import Status, load_post

from .test_publish import SHA, SLUG, approved_post, gh_calls, publisher  # noqa: F401


def _story_jpg(path):
    Image.new("RGB", (1080, 1920), "black").save(path.parent / "story.jpg", "JPEG")


def test_story_body_picks_image_or_video():
    assert Client.story_body("https://x/a.jpg") == {
        "media_type": "STORIES",
        "image_url": "https://x/a.jpg",
    }
    assert Client.story_body("https://x/reel.mp4")["video_url"] == "https://x/reel.mp4"


def test_carousel_story_published_after_feed_post(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    _story_jpg(path)
    p, client, committer, logs = publisher(repo)
    assert p.run(dry_run=False) == 0
    assert client.calls[-4:] == ["get_media", "create_story_container", "wait_finished", "publish"]
    assert client.story_url == (
        f"https://raw.githubusercontent.com/{SLUG}/{SHA}/queue/2026-09-25-post/story.jpg"
    )
    assert committer.commits[-1] == "publish: 2026-09-25-post story"
    post = load_post(path)
    assert post.status == Status.published and post.story_id == "media-1"


def test_story_failure_keeps_post_published(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    _story_jpg(path)
    p, client, committer, logs = publisher(repo)
    client.fail["create_story_container"] = [InstagramError("story boom")] * 5
    assert p.run(dry_run=False) == 0
    post = load_post(path)
    assert post.status == Status.published
    assert post.story_id is None and "story boom" in post.story_error
    assert committer.commits[-1] == "publish: 2026-09-25-post story failed"


def test_no_story_jpg_skips_story(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    p, client, _, logs = publisher(repo)
    assert p.run(dry_run=False) == 0
    assert "create_story_container" not in client.calls
    assert any("story: skipped" in line for line in logs)
    assert load_post(path).story_id is None


def test_dry_run_previews_story(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    _story_jpg(path)
    p, client, committer, logs = publisher(repo)
    assert p.run(dry_run=True) == 0
    text = "\n".join(logs)
    assert '"media_type": "STORIES"' in text and "story.jpg" in text
    assert committer.commits == []


def test_render_story_is_9_16(tmp_path):
    slides = tmp_path / "slides"
    slides.mkdir()
    Image.new("RGB", (1080, 1350), (200, 80, 20)).save(slides / "1.jpg", "JPEG")
    out = render.render_story(tmp_path)
    with Image.open(out) as im:
        assert im.size == (1080, 1920) and im.format == "JPEG"
        # The slide sits in the middle, the blurred backdrop is darker.
        assert sum(im.getpixel((540, 960))) > sum(im.getpixel((540, 40)))
