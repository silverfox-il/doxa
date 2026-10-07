"""`doxa render`, `doxa changed` and `doxa status` against a temporary queue."""

from __future__ import annotations

import datetime as dt

import pytest
from click.testing import CliRunner

from doxa import status
from doxa.cli import main
from doxa.queue import TZ, Status, load_post

from .conftest import make_jpeg, render_post_data, write_post


def run(root, *args):
    return CliRunner().invoke(main, ["--root", str(root), *args])


def prebuilt(root, post_id="2026-09-25-pre", n=3, **kw):
    path = write_post(root, render_post_data(post_id, mode="prebuilt", slides=[], **kw))
    for i in range(1, n + 1):
        make_jpeg(path.parent / "slides" / f"{i}.jpg")
    return path


def test_prebuilt_is_validated_and_marked_rendered(repo):
    path = prebuilt(repo)
    result = run(repo, "render")
    assert result.exit_code == 0, result.output
    assert load_post(path).status == Status.rendered
    assert "`2026-09-25-pre`" in (repo / "STATUS.md").read_text(encoding="utf-8")


def test_bad_prebuilt_fails_and_stays_queued(repo):
    path = prebuilt(repo, n=1)
    result = run(repo, "render")
    assert result.exit_code == 1
    assert "1 slides, need 2-10" in result.output
    assert load_post(path).status == Status.queued


@pytest.mark.parametrize("state", ["publishing", "published", "failed"])
def test_render_never_touches_posts_past_rendered(repo, state):
    path = prebuilt(repo, status=state, approved=True)
    before = path.read_text(encoding="utf-8")
    result = run(repo, "render", "2026-09-25-pre")
    assert result.exit_code == 0, result.output
    assert f"status {state}, not re-rendering" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_render_skips_deleted_ids(repo):
    result = run(repo, "render", "2026-09-30-gone")
    assert result.exit_code == 0
    assert "no post.yaml" in result.output


def test_render_mode_post_end_to_end(repo):
    pytest.importorskip("playwright.sync_api")
    path = write_post(repo, render_post_data())
    result = run(repo, "render", "2026-09-25-test")
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in (path.parent / "slides").iterdir()) == ["1.jpg", "2.jpg"]
    assert load_post(path).status == Status.rendered
    assert run(repo, "validate").exit_code == 0


def test_changed_all_zero_base_lists_every_post(repo):
    prebuilt(repo, "2026-09-25-a")
    prebuilt(repo, "2026-09-26-b")
    result = run(repo, "changed", "0" * 40, "HEAD")
    assert result.output.split() == ["2026-09-25-a", "2026-09-26-b"]


def test_status_table_newest_first_and_next_scheduled(repo):
    prebuilt(repo, "2026-09-25-a", status="published", permalink="https://ig/p/1")
    prebuilt(repo, "2026-09-27-c", publish_at="2026-09-27 07:00", error="boom | bad\nline")
    prebuilt(repo, "2026-09-26-b", publish_at="2026-09-26 07:00", approved=True)
    now = dt.datetime(2026, 9, 25, 12, 0, tzinfo=TZ)
    text = status.build_status(repo / "queue", now)
    rows = [line for line in text.splitlines() if line.startswith("| 2026")]
    assert [r.split("`")[1] for r in rows] == ["2026-09-27-c", "2026-09-26-b", "2026-09-25-a"]
    assert "[link](https://ig/p/1)" in rows[2]
    assert "boom \\| bad line" in rows[0]
    assert "**Next scheduled:** `2026-09-26-b`" in text
    # 2026-09-26-b is approved in YAML but has no approval hash yet.
    assert "| ⚠️ stale |" in rows[1]


def test_changed_unknown_base_falls_back_to_every_post(repo):
    prebuilt(repo, "2026-09-25-a")
    result = run(repo, "changed", "deadbeef", "HEAD")  # tmp dir is not a git repo
    assert result.output.split()[-1] == "2026-09-25-a"


def test_render_rejects_path_like_ids(repo):
    result = run(repo, "render", "../../etc")
    assert result.exit_code == 1
    assert "not a post id" in result.output


def test_one_bad_post_does_not_block_the_others(repo):
    bad = prebuilt(repo, "2026-09-25-bad", n=1)
    good = prebuilt(repo, "2026-09-26-good", publish_at="2026-09-26 07:00")
    result = run(repo, "render")
    assert result.exit_code == 1
    assert "2026-09-25-bad: 1 slides, need 2-10" in result.output
    assert load_post(good).status == Status.rendered
    assert load_post(bad).status == Status.queued


def test_pool_take_copies_unused_photo_and_marks_it(repo):
    import yaml

    pool = repo / "assets" / "pool"
    make_jpeg(pool / "gym-1.jpg")
    make_jpeg(pool / "city-2.jpg")
    (pool / "pool.yaml").write_text(
        "# header kept\n"
        + yaml.safe_dump(
            [
                {"file": "gym-1.jpg", "tags": ["gym"], "used_by": None},
                {"file": "city-2.jpg", "tags": ["city"], "used_by": None},
            ]
        ),
        encoding="utf-8",
    )
    out = run(repo, "pool-take", "2026-10-11-a", "--tag", "city")
    assert out.exit_code == 0, out.output
    assert (repo / "assets" / "backgrounds" / "2026-10-11-a.jpg").is_file()
    text = (pool / "pool.yaml").read_text(encoding="utf-8")
    assert text.startswith("# header kept") and "used_by: 2026-10-11-a" in text
    assert "1 left" in out.output
    assert "gym-1.jpg" in run(repo, "pool-take", "2026-10-12-b", "--tag", "city").output
    assert run(repo, "pool-take", "2026-10-13-c").exit_code == 1  # empty


def test_changed_always_includes_pending_posts(repo):
    # A superseded render run may have skipped these: still queued, or changed
    # since approval. They must render on the next push even if untouched.
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    prebuilt(repo, "2026-09-25-queued")
    prebuilt(repo, "2026-09-26-done", publish_at="2026-09-26 07:00", status="published")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
                   cwd=repo, check=True)
    result = run(repo, "changed", "HEAD", "HEAD")  # empty diff
    assert result.output.split() == ["2026-09-25-queued"]
