"""Queue models, loading, validation and selection.

A "post" is a directory under ``queue/<id>/`` containing ``post.yaml`` and a
``slides/`` folder. ``post.yaml`` has two kinds of fields:

* Owner-authored: ``id``, ``publish_at``, ``approved``, ``mode``, ``caption``,
  ``slides``.
* System-written (never edited by hand): ``status``, ``ig_media_id``,
  ``permalink``, ``published_at``, ``error``.

The pydantic models below are the single source of truth for the schema; the
``doxa validate`` command validates every ``post.yaml`` against them.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import TIMEZONE

TZ = ZoneInfo(TIMEZONE)

# publish_at is written as local Israel wall-clock time, e.g. "2026-09-25 07:00".
PUBLISH_AT_FORMAT = "%Y-%m-%d %H:%M"

# Post ids look like "2026-09-25-manifesto": a date plus a lowercase slug.
POST_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")

# Instagram caption limits (Meta docs, POST /<IG_ID>/media).
CAPTION_MAX_CHARS = 2200
CAPTION_MAX_HASHTAGS = 30
CAPTION_MAX_MENTIONS = 20
_HASHTAG_RE = re.compile(r"(?<![\w#])#\w+")
_MENTION_RE = re.compile(r"(?<![\w@])@[\w.]+")

MIN_SLIDES = 2
MAX_SLIDES = 10


class Mode(str, Enum):
    render = "render"
    prebuilt = "prebuilt"


class Layout(str, Enum):
    bottom = "bottom"
    top = "top"
    list = "list"


class Status(str, Enum):
    queued = "queued"
    rendered = "rendered"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    # Transient failure the publisher is allowed to retry on a later run.
    failed_retryable = "failed-retryable"


# Statuses a post must be in to be eligible for publishing.
PUBLISHABLE_STATUSES = {Status.rendered, Status.failed_retryable}

# Statuses the renderer may (re)write. Anything past this point is owned by the
# publisher; re-rendering it could make an already-published post eligible again.
RENDERABLE_STATUSES = {Status.queued, Status.rendered}


def parse_local(value: str) -> dt.datetime:
    """Parse ``publish_at`` as an aware Asia/Jerusalem datetime.

    Raises ``ValueError`` for bad format and for wall-clock times that do not
    exist because of the spring-forward DST jump (e.g. 02:30 on the last Friday
    before the last Sunday of March). Ambiguous autumn times resolve to the
    first occurrence (``fold=0``).
    """
    naive = dt.datetime.strptime(value, PUBLISH_AT_FORMAT)
    aware = naive.replace(tzinfo=TZ)
    roundtrip = aware.astimezone(dt.UTC).astimezone(TZ)
    if roundtrip.replace(tzinfo=None) != naive:
        raise ValueError(f"{value} does not exist in {TIMEZONE} (DST gap)")
    return aware


class Slide(BaseModel):
    """One carousel slide (only used when ``mode: render``)."""

    model_config = ConfigDict(extra="forbid")

    background: str
    kicker: str = ""
    title: str = ""
    accent: str = ""
    body: str = ""
    layout: Layout = Layout.bottom
    items: list[str] = Field(default_factory=list)

    @field_validator("background")
    @classmethod
    def _background_path(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute() or ".." in p.parts or not v.startswith("assets/"):
            raise ValueError(f"background must be a relative path under assets/, got {v!r}")
        if p.suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError(f"background must be a JPEG, got {v!r}")
        return v

    @model_validator(mode="after")
    def _list_needs_items(self) -> Slide:
        if self.layout == Layout.list and not self.items:
            raise ValueError("layout: list needs at least one entry in items")
        if self.layout != Layout.list and self.items:
            raise ValueError(f"items is only used with layout: list (got {self.layout.value})")
        return self


class Post(BaseModel):
    """A single ``post.yaml``."""

    model_config = ConfigDict(extra="forbid")

    # --- owner-authored ---
    id: str
    publish_at: str
    approved: bool = False
    mode: Mode = Mode.render
    caption: str
    slides: list[Slide] = Field(default_factory=list)

    # --- system-written ---
    status: Status = Status.queued
    ig_media_id: str | None = None
    permalink: str | None = None
    published_at: str | None = None
    error: str | None = None

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not POST_ID_RE.match(v):
            raise ValueError(f"id must look like 2026-09-25-my-slug, got {v!r}")
        return v

    @field_validator("caption")
    @classmethod
    def _caption_limits(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("caption is empty")
        if len(v) > CAPTION_MAX_CHARS:
            raise ValueError(f"caption is {len(v)} chars, max {CAPTION_MAX_CHARS}")
        hashtags = len(_HASHTAG_RE.findall(v))
        if hashtags > CAPTION_MAX_HASHTAGS:
            raise ValueError(f"caption has {hashtags} hashtags, max {CAPTION_MAX_HASHTAGS}")
        mentions = len(_MENTION_RE.findall(v))
        if mentions > CAPTION_MAX_MENTIONS:
            raise ValueError(f"caption has {mentions} @mentions, max {CAPTION_MAX_MENTIONS}")
        return v

    @field_validator("publish_at")
    @classmethod
    def _publish_at_format(cls, v: str) -> str:
        try:
            parse_local(v)
        except ValueError as e:
            raise ValueError(
                f"publish_at must be '{PUBLISH_AT_FORMAT}' in {TIMEZONE} local time: {e}"
            ) from e
        return v

    @model_validator(mode="after")
    def _slides_match_mode(self) -> Post:
        n = len(self.slides)
        if self.mode == Mode.render and not (MIN_SLIDES <= n <= MAX_SLIDES):
            raise ValueError(f"render mode needs {MIN_SLIDES}-{MAX_SLIDES} slides, got {n}")
        if self.mode == Mode.prebuilt and n:
            raise ValueError("prebuilt mode takes JPEGs from slides/; remove the slides: list")
        return self

    @property
    def publish_at_dt(self) -> dt.datetime:
        """``publish_at`` as a timezone-aware Asia/Jerusalem datetime."""
        return parse_local(self.publish_at)

    def is_due(self, now: dt.datetime) -> bool:
        """True when ``publish_at`` has passed relative to ``now`` (aware)."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return self.publish_at_dt <= now


class QueueError(Exception):
    """Raised when a post directory or file is malformed."""


def post_path(queue_dir: Path, post_id: str) -> Path:
    return queue_dir / post_id / "post.yaml"


def load_post(yaml_path: Path) -> Post:
    """Load and validate a single ``post.yaml``.

    Raises :class:`QueueError` with the file path on any parse/validation error
    so callers can report *which* file is broken.
    """
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise QueueError(f"{yaml_path}: invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise QueueError(f"{yaml_path}: top-level document must be a mapping")
    try:
        return Post.model_validate(raw)
    except Exception as e:  # pydantic ValidationError
        raise QueueError(f"{yaml_path}: {e}") from e


def iter_post_files(queue_dir: Path) -> list[Path]:
    """All ``post.yaml`` files under ``queue/``, sorted by id."""
    if not queue_dir.exists():
        return []
    return sorted(queue_dir.glob("*/post.yaml"))


def load_all(queue_dir: Path) -> list[tuple[Path, Post]]:
    """Load every post; raises :class:`QueueError` on the first bad file."""
    return [(p, load_post(p)) for p in iter_post_files(queue_dir)]


class _Dumper(yaml.SafeDumper):
    """SafeDumper that writes multi-line strings (captions, titles) as ``|`` blocks."""


def _str_representer(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str_representer)


def dump_post(post: Post, yaml_path: Path) -> None:
    """Write ``post.yaml`` back with stable key order and block-style multi-line text."""
    data = post.model_dump(mode="json")
    yaml_path.write_text(
        yaml.dump(
            data,
            Dumper=_Dumper,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=1000,
        ),
        encoding="utf-8",
    )


def post_ids_from_paths(paths: list[str]) -> list[str]:
    """Post ids touched by a list of repo-relative paths (e.g. ``git diff --name-only``)."""
    ids: set[str] = set()
    for raw in paths:
        parts = Path(raw.strip()).parts
        if len(parts) >= 3 and parts[0] == "queue":
            ids.add(parts[1])
    return sorted(ids)


def select_publishable(
    posts: list[tuple[Path, Post]], now: dt.datetime
) -> tuple[Path, Post] | None:
    """Pick the single post to publish this run, or ``None``.

    Rules (see spec §5): ``approved: true``, status in {rendered,
    failed-retryable}, and ``publish_at <= now``. If several qualify, the one
    with the earliest ``publish_at`` wins (oldest debt first).
    """
    eligible = [
        (path, post)
        for path, post in posts
        if post.approved and post.status in PUBLISHABLE_STATUSES and post.is_due(now)
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda pp: pp[1].publish_at_dt)
    return eligible[0]
