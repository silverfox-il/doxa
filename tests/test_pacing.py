"""Account safety: gaps, daily cap, quiet hours, pause after an Instagram block."""

from __future__ import annotations

import datetime as dt

from doxa import pacing
from doxa.instagram import ActionBlockedError
from doxa.pacing import Pacing
from doxa.queue import TZ, Post, Status, load_post

from .conftest import render_post_data
from .test_publish import approved_post, gh_calls, publisher  # noqa: F401

CFG = Pacing(min_gap_minutes=120, max_per_24h=4, quiet_start="00:00", quiet_end="08:00")


def at(h, m=0, day=5):
    return dt.datetime(2026, 10, day, h, m, tzinfo=TZ)


def published(pid, when):
    data = render_post_data(
        pid,
        status="published",
        published_at=when.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S+0000"),
    )
    return Post.model_validate(data)


def test_meta_timestamps_parse():
    (t,) = pacing.published_times([published("2026-10-05-a", at(9))])
    assert t == at(9)


def test_min_gap_between_posts(tmp_path):
    posts = [published("2026-10-05-a", at(9))]
    assert any("min ago" in r for r in pacing.gate(tmp_path, posts, at(10, 30), CFG))
    assert pacing.gate(tmp_path, posts, at(11, 1), CFG) == []


def test_daily_cap(tmp_path):
    posts = [published(f"2026-10-05-p{i}", at(9 + 3 * i)) for i in range(4)]
    assert any("max 4" in r for r in pacing.gate(tmp_path, posts, at(23, 0), CFG))
    # 24 hours after the first one, a slot frees up.
    assert not any("max 4" in r for r in pacing.gate(tmp_path, posts, at(9, 1, day=6), CFG))


def test_quiet_hours(tmp_path):
    assert any("quiet" in r for r in pacing.gate(tmp_path, [], at(3), CFG))
    assert pacing.gate(tmp_path, [], at(8), CFG) == []


def test_pause_file_holds_everything_until_it_expires(tmp_path):
    pacing.write_pause(tmp_path, at(22, 30), "Instagram restricted activity")
    assert any("paused until" in r for r in pacing.gate(tmp_path, [], at(21), CFG))
    assert pacing.gate(tmp_path, [], at(22, 31), CFG) == []


def test_block_pauses_publisher_and_keeps_post_retryable(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    p, client, committer, logs = publisher(repo)
    p.pacing = Pacing(
        min_gap_minutes=0,
        max_per_24h=100,
        quiet_start="00:00",
        quiet_end="00:00",
        block_pause_hours=24,
    )
    client.fail["publish"] = [ActionBlockedError("code=4 subcode=2207051: restricted")]
    assert p.run(dry_run=False) == 1
    post = load_post(path)
    assert post.status == Status.failed_retryable and "2207051" in post.error
    pause = pacing.read_pause(repo)
    assert pause is not None and pause[0] > p.now
    assert any(c.startswith("publish: pause until") for c in committer.commits)
    # The next run publishes nothing while paused.
    p2, client2, _, logs2 = publisher(repo)
    p2.pacing = p.pacing
    assert p2.run(dry_run=False) == 0
    assert "publish" not in client2.calls
    assert any("PACING: paused until" in line for line in logs2)


def test_pacing_holds_live_runs_but_dry_run_still_previews(repo, gh_calls):  # noqa: F811
    approved_post(repo)
    pacing.write_pause(repo, dt.datetime(2030, 1, 1, tzinfo=TZ), "test")
    p, client, _, logs = publisher(repo)
    assert p.run(dry_run=True) == 0
    assert any("a live run would publish" in line or "dry run complete" in line for line in logs)
    p2, client2, _, logs2 = publisher(repo)
    assert p2.run(dry_run=False) == 0 and "publish" not in client2.calls


def test_restricted_error_but_post_is_live_counts_as_published(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    p, client, committer, logs = publisher(repo)
    client.fail["publish"] = [ActionBlockedError("code=4 subcode=2207051: restricted")]
    caption = load_post(path).caption
    client.recent = [
        # An older copy of the same caption must not count...
        {"id": "old", "caption": caption, "timestamp": "2026-09-20T06:00:00+0000"},
        # ...the one created just now does.
        {
            "id": "new-1",
            "caption": caption,
            "permalink": "https://www.instagram.com/p/NEW/",
            "timestamp": p.now.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S+0000"),
        },
    ]
    assert p.run(dry_run=False) == 0
    post = load_post(path)
    assert post.status == Status.published and post.ig_media_id == "new-1"
    assert pacing.read_pause(repo) is None


def test_restricted_error_and_not_live_pauses(repo, gh_calls):  # noqa: F811
    path = approved_post(repo)
    p, client, committer, logs = publisher(repo)
    client.fail["publish"] = [ActionBlockedError("code=4 subcode=2207051: restricted")]
    client.recent = [
        {"id": "old", "caption": load_post(path).caption, "timestamp": "2026-09-20T06:00:00+0000"}
    ]
    assert p.run(dry_run=False) == 1
    assert load_post(path).status == Status.failed_retryable
    assert pacing.read_pause(repo) is not None


def test_overdue_reels_go_before_overdue_carousels(repo, gh_calls, monkeypatch):  # noqa: F811
    from .test_publish import reel_post

    carousel = approved_post(repo, "2026-09-25-older", publish_at="2026-09-25 06:00")
    reel_path = reel_post(repo, monkeypatch)  # 2026-09-25-post at 07:00, a reel
    p, client, _, _ = publisher(
        repo, head=lambda u: (200, "video/mp4" if u.endswith(".mp4") else "image/jpeg")
    )
    client.create_reel_container = lambda url, caption: "reel-parent"
    assert p.run(dry_run=False) == 0
    assert load_post(reel_path).status == Status.published
    assert load_post(carousel).status != Status.published
