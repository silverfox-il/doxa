"""Approval-issue flow (spec §4) — the safety bezel.

After rendering, ``render.yml`` opens (or updates) one GitHub Issue per post,
titled ``Approve: <id>``, showing every slide (commit-pinned raw URLs), the
caption and ``publish_at``. GitHub emails the owner. The owner approves by:

1. setting ``approved: true`` in ``post.yaml``; or
2. adding the ``approved`` label to the issue — ``approve.yml`` then runs
   :func:`sync_label_to_yaml`, which writes ``approved: true`` back.

Nothing with ``approved: false`` is ever published.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import TIMEZONE, github
from .queue import Post, dump_post, load_post

APPROVED_LABEL = "approved"
APPROVED_LABEL_COLOR = "2ea44f"
TITLE_PREFIX = "Approve: "
_TITLE_RE = re.compile(r"^Approve: (\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*)$")


def issue_title(post_id: str) -> str:
    return f"{TITLE_PREFIX}{post_id}"


def post_id_from_title(title: str) -> str | None:
    """Inverse of :func:`issue_title`; ``None`` for anything else (untrusted input)."""
    m = _TITLE_RE.match(title)
    return m.group(1) if m else None


def build_issue_body(post: Post, slug: str, sha: str, n_slides: int) -> str:
    """Markdown body: state, schedule, slide previews, caption, how to approve."""
    state = (
        "✅ **Approved** — will publish at the time below."
        if post.approved
        else "⏳ **Waiting for approval** — nothing publishes until you approve."
    )
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
        "To change the post, edit `post.yaml` and push: slides re-render and this "
        "issue updates.",
    ]
    return "\n".join(lines)


def upsert_approval_issue(post: Post, slug: str, sha: str, n_slides: int) -> tuple[int, bool]:
    """Create the approval issue or refresh its body. Returns (number, created)."""
    title = issue_title(post.id)
    body = build_issue_body(post, slug, sha, n_slides)
    existing = github.find_open_issue(title)
    if existing is None:
        return github.create_issue(title, body), True
    github.update_issue_body(existing, body)
    return existing, False


def ensure_approved_label() -> None:
    github.ensure_label(
        APPROVED_LABEL, APPROVED_LABEL_COLOR, "DOXA: owner approved this post for publishing"
    )


def sync_label_to_yaml(post_id: str, yaml_path: Path) -> bool:
    """Set ``approved: true`` if the open approval issue has the ``approved`` label.

    Returns True when ``post.yaml`` changed. Only ever flips false -> true;
    removing the label does not un-approve (edit ``post.yaml`` for that).
    """
    number = github.find_open_issue(issue_title(post_id))
    if number is None or APPROVED_LABEL not in github.issue_labels(number):
        return False
    post = load_post(yaml_path)
    if post.approved:
        return False
    post.approved = True
    dump_post(post, yaml_path)
    return True
