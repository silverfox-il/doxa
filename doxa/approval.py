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

import re
from pathlib import Path

from . import TIMEZONE, github
from .queue import Post, approval_is_current, content_hash, dump_post, load_post

APPROVED_LABEL = "approved"
APPROVED_LABEL_COLOR = "2ea44f"
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


def reconcile(post: Post, post_dir: Path) -> str | None:
    """Bring ``approved``/``approved_hash`` in line with the current content.

    Mutates ``post`` and returns what happened, or ``None`` if nothing did:

    * ``"stamped"`` — owner set ``approved: true`` by hand; record the hash.
    * ``"reset"``   — content changed since approval; un-approve.
    * ``"cleared"`` — not approved but a hash lingered; drop it.
    """
    current = content_hash(post, post_dir)
    if post.approved and post.approved_hash is None:
        post.approved_hash = current
        return "stamped"
    if post.approved and post.approved_hash != current:
        post.approved = False
        post.approved_hash = None
        return "reset"
    if not post.approved and post.approved_hash is not None:
        post.approved_hash = None
        return "cleared"
    return None


def build_issue_body(post: Post, post_dir: Path, slug: str, sha: str, n_slides: int) -> str:
    """Markdown body: state, schedule, slide previews, caption, how to approve."""
    if approval_is_current(post, post_dir):
        state = f"{APPROVED_MARK} — will publish at the time below."
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
        f"- **Rendered from:** `{sha[:7]}`",
        "",
        "### Slides",
        "",
    ]
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
    if approval_is_current(post, yaml_path.parent):
        return False
    post.approved = True
    post.approved_hash = content_hash(post, yaml_path.parent)
    dump_post(post, yaml_path)
    return True
