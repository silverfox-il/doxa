"""Failure alerts (spec §6): one rolling GitHub Issue the owner gets emailed about.

A failed workflow step calls ``doxa alert``. The first failure opens the issue
``🚨 DOXA failure``; a *different* failure later adds a comment (so a new
problem always emails the owner); the same failure repeating every hour only
updates a counter in the issue body, so there is no hourly email storm.
Messages come from the publisher's own error lines, which never contain the
token.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re

from . import github
from .queue import TZ

FAILURE_TITLE = "🚨 DOXA failure"
_FP_RE = re.compile(r"<!-- doxa-fingerprint: (\w+) count: (\d+) -->")

# Known causes the owner can fix, with what to do (shown at the top of the issue).
HINTS = [
    (
        "code=190",
        "The Instagram access token is no longer valid (password change, logout, or Meta "
        "security reset). Generate a new long-lived token and save it as the repository "
        "secret IG_ACCESS_TOKEN, then run the healthcheck workflow.",
    ),
    (
        "2207051",
        "Instagram restricted the account's activity (spam protection, usually after "
        "posting too fast). The publisher paused itself for 24 hours (state/pause.yaml) "
        "and keeps the post for later. Avoid bulk activity on the account meanwhile; if the "
        "app offers 'Tell us', report it as a mistake.",
    ),
    (
        "QuotaExceeded",
        "Instagram's 24-hour publishing limit is used up. Nothing to do: it resumes by itself.",
    ),
]


def _run_link() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "(local run)"


def summarize(log: str) -> str:
    """The error lines of a run log (✗ lines), or its tail if there are none."""
    lines = [line for line in log.splitlines() if line.lstrip().startswith("✗")]
    if not lines:
        lines = log.strip().splitlines()[-5:]
    return "\n".join(lines)[:1500] or "(no output)"


def fingerprint(step: str, error: str) -> str:
    # Ignore numbers and hex ids so the same problem on another post/run matches.
    norm = re.sub(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+", "<post>", f"{step}|{error}")
    norm = re.sub(r"[0-9a-f]{7,}|\d+", "#", norm)
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def hint_for(error: str) -> str | None:
    return next((text for key, text in HINTS if key in error), None)


def report_failure(step: str, error: str, now: dt.datetime | None = None) -> str:
    """Open, comment on, or bump the rolling failure issue. Returns what it did."""
    now = (now or dt.datetime.now(TZ)).astimezone(TZ)
    fp = fingerprint(step, error)
    hint = hint_for(error)
    details = "\n".join(
        [
            f"**Step:** {step}",
            f"**When:** {now:%Y-%m-%d %H:%M} (Asia/Jerusalem)",
            f"**Run:** {_run_link()}",
            "",
            *([f"**What to do:** {hint}", ""] if hint else []),
            "```",
            error,
            "```",
        ]
    )
    number = github.find_open_issue(FAILURE_TITLE)
    if number is None:
        body = (
            f"<!-- doxa-fingerprint: {fp} count: 1 -->\n{details}\n\nClose this issue once fixed."
        )
        github.create_issue(FAILURE_TITLE, body)
        return "opened"
    old = github.issue_body(number)
    m = _FP_RE.search(old)
    if m and m.group(1) == fp:
        count = int(m.group(2)) + 1
        github.update_issue_body(
            number,
            f"<!-- doxa-fingerprint: {fp} count: {count} -->\n{details}\n\n"
            f"Same failure {count} times in a row. Close this issue once fixed.",
        )
        return "bumped"
    github.update_issue_body(
        number,
        f"<!-- doxa-fingerprint: {fp} count: 1 -->\n{details}\n\nClose this issue once fixed.",
    )
    github.comment_issue(number, details)
    return "commented"
