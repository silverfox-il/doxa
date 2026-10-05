"""Account safety: how fast the publisher may post.

Instagram restricted the account on 2026-10-04 (HTTP 403 code=4
subcode=2207051, "We restrict certain activity to protect our community")
after 13 posts in about 28 hours on a brand-new account. From then on:

* a minimum gap between feed posts and a cap per rolling 24 hours,
* no posting in the night (quiet hours),
* after an Instagram block, a pause of the whole publisher (``state/pause.yaml``)
  so retries never hammer a restricted account.

A post held back by pacing is simply published later, oldest first; its
``publish_at`` and approval do not change. Limits live in ``config/publish.yaml``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml

from .queue import TZ, Post, Status

PAUSE_FILE = Path("state") / "pause.yaml"


@dataclass
class Pacing:
    min_gap_minutes: int = 180
    max_per_24h: int = 4
    quiet_start: str = "00:00"  # local time, no posting from ...
    quiet_end: str = "08:00"  # ... until
    block_pause_hours: int = 24

    @classmethod
    def load(cls, root: Path) -> Pacing:
        path = root / "config" / "publish.yaml"
        if not path.is_file():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(**data)


def published_times(posts: list[Post]) -> list[dt.datetime]:
    """When each published post went out (aware datetimes)."""
    out = []
    for post in posts:
        if post.status == Status.published and post.published_at:
            stamp = post.published_at.replace("Z", "+00:00")
            if len(stamp) > 5 and stamp[-5] in "+-" and stamp[-3] != ":":
                stamp = stamp[:-2] + ":" + stamp[-2:]  # Meta's +0000 -> +00:00
            try:
                out.append(dt.datetime.fromisoformat(stamp))
            except ValueError:
                continue
    return out


def _clock(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def in_quiet_hours(now: dt.datetime, cfg: Pacing) -> bool:
    t = now.astimezone(TZ).time()
    start, end = _clock(cfg.quiet_start), _clock(cfg.quiet_end)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def read_pause(root: Path) -> tuple[dt.datetime, str] | None:
    path = root / PAUSE_FILE
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    until = data.get("until")
    if not until:
        return None
    return dt.datetime.fromisoformat(str(until)), str(data.get("reason", ""))


def write_pause(root: Path, until: dt.datetime, reason: str) -> Path:
    path = root / PAUSE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"until": until.astimezone(TZ).isoformat(timespec="minutes"), "reason": reason}
    path.write_text(
        "# Written by the publisher after an Instagram block. Nothing publishes until\n"
        "# `until`. Delete this file to resume earlier (owner's call).\n"
        + yaml.safe_dump(body, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def gate(root: Path, posts: list[Post], now: dt.datetime, cfg: Pacing) -> list[str]:
    """Reasons the publisher must not post anything right now (empty = go)."""
    out = []
    pause = read_pause(root)
    if pause is not None and now < pause[0]:
        out.append(f"paused until {pause[0].astimezone(TZ):%Y-%m-%d %H:%M} ({pause[1]})")
    if in_quiet_hours(now, cfg):
        out.append(f"quiet hours {cfg.quiet_start}-{cfg.quiet_end}")
    times = sorted(published_times(posts))
    if times:
        gap = now - times[-1]
        need = dt.timedelta(minutes=cfg.min_gap_minutes)
        if gap < need:
            nxt = (times[-1] + need).astimezone(TZ)
            out.append(f"last post {int(gap.total_seconds() // 60)} min ago; next from {nxt:%H:%M}")
    recent = [t for t in times if now - t < dt.timedelta(hours=24)]
    if len(recent) >= cfg.max_per_24h:
        out.append(f"{len(recent)} posts in the last 24h (max {cfg.max_per_24h})")
    return out
