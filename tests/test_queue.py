"""Schema, time-zone and selection rules for queue/<id>/post.yaml."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError

from doxa.queue import (
    TZ,
    Post,
    Status,
    dump_post,
    load_post,
    parse_local,
    post_ids_from_paths,
    select_publishable,
)

from .conftest import render_post_data, write_post


def post(**overrides) -> Post:
    return Post.model_validate(render_post_data(**overrides))


# --- schema ---------------------------------------------------------------


def test_minimal_render_post_defaults():
    p = post()
    assert p.approved is False
    assert p.status == Status.queued
    assert p.ig_media_id is None and p.error is None


def test_unknown_field_rejected():
    with pytest.raises(ValidationError, match="extra"):
        post(aproved=True)  # typo must not silently pass


@pytest.mark.parametrize("bad_id", ["manifesto", "2026-9-25-x", "2026-09-25-Bad", "2026-09-25-"])
def test_id_format(bad_id):
    with pytest.raises(ValidationError, match="id must look like"):
        Post.model_validate(render_post_data(bad_id))


def test_caption_limits():
    with pytest.raises(ValidationError, match="max 2200"):
        post(caption="א" * 2201)
    with pytest.raises(ValidationError, match="hashtags"):
        post(caption=" ".join(f"#t{i}" for i in range(31)))
    with pytest.raises(ValidationError, match="mentions"):
        post(caption=" ".join(f"@u{i}" for i in range(21)))
    with pytest.raises(ValidationError, match="empty"):
        post(caption="   \n")
    # Exactly at the limits is fine; an email address is not a mention.
    post(caption=" ".join(f"#t{i}" for i in range(30)) + " a@b.com")


@pytest.mark.parametrize("n", [1, 11])
def test_render_slide_count(n):
    slide = {"background": "assets/backgrounds/bg.jpg", "title": "x"}
    with pytest.raises(ValidationError, match="2-10 slides"):
        post(slides=[slide] * n)


def test_prebuilt_must_not_list_slides():
    with pytest.raises(ValidationError, match="prebuilt"):
        post(mode="prebuilt")
    assert post(mode="prebuilt", slides=[]).mode.value == "prebuilt"


@pytest.mark.parametrize(
    "bg", ["/etc/x.jpg", "assets/../secrets.jpg", "queue/x.jpg", "assets/backgrounds/x.png"]
)
def test_background_path_rules(bg):
    with pytest.raises(ValidationError, match="background"):
        post(slides=[{"background": bg}] * 2)


def test_list_layout_needs_items():
    bg = "assets/backgrounds/bg.jpg"
    with pytest.raises(ValidationError, match="needs at least one"):
        post(slides=[{"background": bg, "layout": "list"}] * 2)
    with pytest.raises(ValidationError, match="only used with layout: list"):
        post(slides=[{"background": bg, "items": ["a"]}] * 2)


# --- time zone ------------------------------------------------------------


def test_publish_at_is_israel_local_time():
    # Summer (IDT, UTC+3) and winter (IST, UTC+2).
    assert parse_local("2026-09-25 07:00").astimezone(dt.UTC).hour == 4
    assert parse_local("2026-12-01 07:00").astimezone(dt.UTC).hour == 5


def test_publish_at_rejects_dst_gap():
    # Israel springs forward 02:00 -> 03:00 on Friday 2026-03-27.
    with pytest.raises(ValueError, match="DST gap"):
        parse_local("2026-03-27 02:30")
    with pytest.raises(ValidationError, match="DST gap"):
        post(publish_at="2026-03-27 02:30")
    assert parse_local("2026-03-27 03:00").utcoffset() == dt.timedelta(hours=3)


def test_publish_at_ambiguous_hour_takes_first_occurrence():
    # Clocks go back 02:00 -> 01:00 on Sunday 2026-10-25; 01:30 happens twice.
    first = parse_local("2026-10-25 01:30")
    assert first.utcoffset() == dt.timedelta(hours=3)


@pytest.mark.parametrize(
    "bad", ["2026-09-25", "2026-09-25T07:00", "25/09/2026 07:00", "2026-09-25 7am"]
)
def test_publish_at_format(bad):
    with pytest.raises(ValidationError, match="publish_at"):
        post(publish_at=bad)


def test_is_due_compares_instants_not_wall_clocks():
    p = post(publish_at="2026-09-25 07:00")
    utc_before = dt.datetime(2026, 9, 25, 3, 59, tzinfo=dt.UTC)
    utc_after = dt.datetime(2026, 9, 25, 4, 0, tzinfo=dt.UTC)
    assert not p.is_due(utc_before)
    assert p.is_due(utc_after)
    with pytest.raises(ValueError, match="aware"):
        p.is_due(dt.datetime(2026, 9, 25, 8, 0))


# --- selection ------------------------------------------------------------

NOW = dt.datetime(2026, 9, 25, 9, 0, tzinfo=TZ)


def _pp(post_id: str, **kw) -> tuple[Path, Post]:
    return Path(f"queue/{post_id}/post.yaml"), Post.model_validate(render_post_data(post_id, **kw))


def test_select_requires_approval_status_and_due_time():
    posts = [
        _pp(
            "2026-09-20-unapproved",
            approved=False,
            status="rendered",
            publish_at="2026-09-20 07:00",
        ),
        _pp("2026-09-21-queued", approved=True, status="queued", publish_at="2026-09-21 07:00"),
        _pp(
            "2026-09-22-published", approved=True, status="published", publish_at="2026-09-22 07:00"
        ),
        _pp(
            "2026-09-23-publishing",
            approved=True,
            status="publishing",
            publish_at="2026-09-23 07:00",
        ),
        _pp("2026-09-24-failed", approved=True, status="failed", publish_at="2026-09-24 07:00"),
        _pp("2026-09-26-future", approved=True, status="rendered", publish_at="2026-09-26 07:00"),
    ]
    assert select_publishable(posts, NOW) is None


def test_select_picks_oldest_due_and_allows_retryable():
    posts = [
        _pp("2026-09-25-today", approved=True, status="rendered", publish_at="2026-09-25 07:00"),
        _pp(
            "2026-09-24-retry",
            approved=True,
            status="failed-retryable",
            publish_at="2026-09-24 07:00",
        ),
    ]
    chosen = select_publishable(posts, NOW)
    assert chosen is not None and chosen[1].id == "2026-09-24-retry"


# --- io -------------------------------------------------------------------


def test_dump_roundtrip_keeps_hebrew_and_block_caption(repo):
    path = write_post(repo, render_post_data())
    p = load_post(path)
    p.status = Status.rendered
    dump_post(p, path)
    text = path.read_text(encoding="utf-8")
    assert "caption: |" in text
    assert "שורה ראשונה" in text  # not \u-escaped
    assert load_post(path) == p


def test_post_ids_from_paths():
    paths = [
        "queue/2026-09-25-a/post.yaml",
        "queue/2026-09-25-a/slides/1.jpg",
        "queue/2026-09-26-b/post.yaml\n",
        "README.md",
        "queue/README.md",
    ]
    assert post_ids_from_paths(paths) == ["2026-09-25-a", "2026-09-26-b"]
