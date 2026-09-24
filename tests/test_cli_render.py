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
