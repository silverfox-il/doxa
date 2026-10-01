"""Approval-issue flow (spec §4) — the safety bezel.

After rendering, ``render.yml`` opens (or updates) one GitHub Issue per post,
titled ``Approve: <id>``, showing every slide (commit-pinned raw URLs), the
caption and ``publish_at``. GitHub emails the owner. The owner approves by:

1. setting ``approved: true`` in ``post.yaml``; or
2. adding the ``approved`` label to the issue — ``approve.yml`` then runs
   :func:`sync_label_to_yaml`, which writes ``approved: true`` back.

Either way the system stamps ``approved_hash`` with the post's content hash.
Any later edit changes the hash; :func:`reconcile` (run on every render) then
resets ``approved`` to false and the issue asks for approval again. Nothing
with ``approved: false`` or a stale hash is ever published.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import TIMEZONE, github
from .queue import (
    TZ,
    ApprovedBy,
    Post,
    approval_is_current,
    content_hash,
    dump_post,
    load_post,
)

APPROVED_LABEL = "approved"
APPROVED_LABEL_COLOR = "2ea44f"
AUTO_LABEL = "auto-approved"
AUTO_LABEL_COLOR = "1d76db"
# Owner veto: an issue with this label never publishes, approved or not.
HOLD_LABEL = "hold"
HOLD_LABEL_COLOR = "d93f0b"
# An auto-approved post waits this long before it may publish, so the owner
# always has a day to look at the issue and add `hold`.
AUTO_VETO_HOURS = 24
TITLE_PREFIX = "Approve: "
APPROVED_MARK = "✅ **Approved**"
RESET_COMMENT = (
    "⚠️ **Approval reset.** The post changed after it was approved, so it will not "
    "publish. I removed the `approved` label: review the updated slides above and "
    "add it again to approve."
)
_TITLE_RE = re.compile(r"^Approve: (\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*)$")


def issue_title(post_id: str) -> str:
    return f"{TITLE_PREFIX}{post_id}"


def post_id_from_title(title: str) -> str | None:
    """Inverse of :func:`issue_title`; ``None`` for anything else (untrusted input)."""
    m = _TITLE_RE.match(title)
    return m.group(1) if m else None


def stamp(post: Post, post_dir: Path, by: ApprovedBy, now: dt.datetime) -> None:
    """Approve ``post`` for its current content."""
    post.approved = True
    post.approved_hash = content_hash(post, post_dir)
    post.approved_by = by
    post.approved_at = now.astimezone(TZ).isoformat(timespec="seconds")


def clear(post: Post) -> None:
    post.approved = False
    post.approved_hash = None
    post.approved_by = None
    post.approved_at = None


def reconcile(post: Post, post_dir: Path, now: dt.datetime | None = None) -> str | None:
    """Bring ``approved``/``approved_hash`` in line with the current content.

    Mutates ``post`` and returns what happened, or ``None`` if nothing did:

    * ``"stamped"`` — owner set ``approved: true`` by hand; record the hash.
    * ``"reset"``   — content changed since approval; un-approve.
    * ``"cleared"`` — not approved but a hash lingered; drop it.
    """
    now = now or dt.datetime.now(TZ)
    current = content_hash(post, post_dir)
    if post.approved and post.approved_hash is None:
        stamp(post, post_dir, ApprovedBy.owner, now)
        return "stamped"
    if post.approved and post.approved_hash != current:
        clear(post)
        return "reset"
    if not post.approved and (post.approved_hash or post.approved_by or post.approved_at):
        clear(post)
        return "cleared"
    return None


def auto_veto_until(post: Post) -> dt.datetime | None:
    """When an auto-approved post becomes publishable (None if not auto-approved)."""
    if post.approved_by != ApprovedBy.auto or not post.approved_at:
        return None
    return dt.datetime.fromisoformat(post.approved_at) + dt.timedelta(hours=AUTO_VETO_HOURS)


def build_issue_body(post: Post, post_dir: Path, slug: str, sha: str, n_slides: int) -> str:
    """Markdown body: state, schedule, slide previews, caption, how to approve."""
    if approval_is_current(post, post_dir):
        state = f"{APPROVED_MARK} — will publish at the time below."
        until = auto_veto_until(post)
        if until is not None:
            state += (
                f"\n\n🤖 Approved automatically (all checks passed). To stop it, add the "
                f"`{HOLD_LABEL}` label. It cannot publish before "
                f"{until:%Y-%m-%d %H:%M} ({TIMEZONE})."
            )
    elif post.approved:
        state = "⚠️ **Approval is stale** — the post changed after approval and will not publish."
    else:
        state = "⏳ **Waiting for approval** — nothing publishes until you approve."
    lines = [
        state,
        "",
        f"- **Post:** `{post.id}`",
        f"- **Publish at:** {post.publish_at} ({TIMEZONE})",
        f"- **Mode:** {post.mode.value} · **Slides:** {n_slides} · **Status:** "
        f"{post.status.value}",
        f"- **Content rules:** see `doxa rules {post.id}`",
        f"- **Rendered from:** `{sha[:7]}`",
        "",
    ]
    if post.source is not None:
        lines[-1:-1] = [f"- **Source:** {post.source.file}, {post.source.section}"]
    if post.reel is not None:
        url = github.raw_file_url(slug, sha, post.id, "reel.mp4")
        lines += [
            f"### Reel ({post.reel.duration:.1f}s, music: {post.reel.music})",
            "",
            f"▶️ [Watch the video]({url})",
            "",
            *[f"> {line}" for line in post.reel.lines],
            "",
        ]
    else:
        lines += ["### Slides", ""]
    for i in range(1, n_slides + 1):
        lines.append(f"**{i}/{n_slides}**  ")
        lines.append(f'<img src="{github.raw_url(slug, sha, post.id, i)}" width="360">')
        lines.append("")
    # A fence longer than any backtick run in the caption keeps it verbatim.
    longest = max((len(m) for m in re.findall(r"`+", post.caption)), default=0)
    fence = "`" * max(3, longest + 1)
    lines += [
        "### Caption",
        "",
        fence,
        post.caption.rstrip("\n"),
        fence,
        "",
        "---",
        "**To approve**, either:",
        f"- add the `{APPROVED_LABEL}` label to this issue, or",
        f"- set `approved: true` in `queue/{post.id}/post.yaml`.",
        "",
        "To change the post, edit `post.yaml` and push: slides re-render, this issue "
        "updates, and any earlier approval is reset.",
    ]
    return "\n".join(lines)


def upsert_approval_issue(
    post: Post, post_dir: Path, slug: str, sha: str, n_slides: int
) -> tuple[int, bool]:
    """Create the approval issue or refresh its body. Returns (number, created).

    When an issue that showed "Approved" no longer does, remove the
    ``approved`` label (so re-adding it fires a fresh label event) and comment,
    so the owner gets an email saying the approval was reset.
    """
    title = issue_title(post.id)
    body = build_issue_body(post, post_dir, slug, sha, n_slides)
    existing = github.find_open_issue(title)
    if existing is None:
        return github.create_issue(title, body), True
    was_approved = github.issue_body(existing).startswith(APPROVED_MARK)
    github.update_issue_body(existing, body)
    if was_approved and not body.startswith(APPROVED_MARK):
        if APPROVED_LABEL in github.issue_labels(existing):
            github.remove_label(existing, APPROVED_LABEL)
        github.comment_issue(existing, RESET_COMMENT)
    return existing, False


def ensure_approved_label() -> None:
    github.ensure_label(
        APPROVED_LABEL, APPROVED_LABEL_COLOR, "DOXA: owner approved this post for publishing"
    )


def sync_label_to_yaml(post_id: str, yaml_path: Path) -> bool:
    """Approve the post if its open approval issue has the ``approved`` label.

    Stamps ``approved_hash`` with the current content so later edits reset
    it. Returns True when ``post.yaml`` changed. Only ever approves; removing
    the label does not un-approve (edit ``post.yaml`` for that).
    """
    number = github.find_open_issue(issue_title(post_id))
    if number is None or APPROVED_LABEL not in github.issue_labels(number):
        return False
    post = load_post(yaml_path)
    if approval_is_current(post, yaml_path.parent) and post.approved_by == ApprovedBy.owner:
        return False
    # An owner label also upgrades an auto-approval: no 24-hour wait.
    stamp(post, yaml_path.parent, ApprovedBy.owner, dt.datetime.now(TZ))
    dump_post(post, yaml_path)
    return True


def ensure_labels() -> None:
    ensure_approved_label()
    github.ensure_label(AUTO_LABEL, AUTO_LABEL_COLOR, "DOXA: approved automatically")
    github.ensure_label(HOLD_LABEL, HOLD_LABEL_COLOR, "DOXA: owner veto, never publish")
