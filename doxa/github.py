"""Thin wrapper over the ``gh`` CLI.

Every GitHub mutation goes through ``gh`` so this code never handles a token:
Actions puts ``GH_TOKEN`` in the environment and ``gh`` reads it. Functions are
small shell-outs; flows live in :mod:`doxa.approval`. Tests replace :func:`_gh`.
"""

from __future__ import annotations

import json
import os
import subprocess


class GitHubError(Exception):
    pass


def repo_slug() -> str:
    """``owner/repo`` from ``GITHUB_REPOSITORY`` or the git ``origin`` remote."""
    env = os.environ.get("GITHUB_REPOSITORY")
    if env:
        return env
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitHubError(f"cannot determine repo slug: {e.stderr}") from e
    slug = url.rsplit("github.com", 1)[-1].lstrip(":/")
    return slug.removesuffix(".git")


def raw_url(slug: str, sha: str, post_id: str, n: int) -> str:
    """Commit-pinned raw URL for slide ``n`` (spec §5)."""
    return f"https://raw.githubusercontent.com/{slug}/{sha}/queue/{post_id}/slides/{n}.jpg"


def _gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        # Name only the subcommand: argv can hold a whole issue body.
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def find_open_issue(title: str) -> int | None:
    """Number of the oldest open issue whose title is exactly ``title``.

    Uses the issue list (not search) so an issue created seconds ago is found;
    search results lag and would let a re-run open a duplicate.
    """
    out = _gh(["issue", "list", "--state", "open", "--limit", "500", "--json", "number,title"])
    matches = [int(i["number"]) for i in json.loads(out or "[]") if i.get("title") == title]
    return min(matches) if matches else None


def create_issue(title: str, body: str) -> int:
    out = _gh(["issue", "create", "--title", title, "--body", body])
    # `gh issue create` prints the new issue URL; its last segment is the number.
    return int(out.strip().splitlines()[-1].rsplit("/", 1)[-1])


def update_issue_body(number: int, body: str) -> None:
    _gh(["issue", "edit", str(number), "--body", body])


def close_issue(number: int, comment: str) -> None:
    _gh(["issue", "close", str(number), "--comment", comment])


def issue_body(number: int) -> str:
    out = _gh(["issue", "view", str(number), "--json", "body"])
    return json.loads(out or "{}").get("body", "")


def comment_issue(number: int, body: str) -> None:
    _gh(["issue", "comment", str(number), "--body", body])


def issue_labels(number: int) -> set[str]:
    out = _gh(["issue", "view", str(number), "--json", "labels"])
    return {lbl["name"] for lbl in json.loads(out or "{}").get("labels", [])}


def remove_label(number: int, label: str) -> None:
    _gh(["issue", "edit", str(number), "--remove-label", label])


def ensure_label(name: str, color: str, description: str) -> None:
    """Create the label if missing (``--force`` makes this idempotent)."""
    _gh(["label", "create", name, "--color", color, "--description", description, "--force"])
