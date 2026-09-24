"""Approval-issue flow (spec §4) against an in-memory fake of the `gh` CLI."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from doxa import approval, github
from doxa.cli import main
from doxa.queue import Post, load_post

from .conftest import make_jpeg, render_post_data, write_post

SHA = "0123456789abcdef0123456789abcdef01234567"
SLUG = "silverfox-il/doxa"


class FakeGh:
    """Just enough of `gh issue` / `gh label` to exercise the flow."""

    def __init__(self) -> None:
        self.issues: dict[int, dict] = {}
        self.labels: set[str] = set()
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        opts = dict(zip(args[2::2], args[3::2], strict=False))
        match args[:2]:
            case ["issue", "list"]:
                open_ = [
                    {"number": n, "title": i["title"]}
                    for n, i in self.issues.items()
                    if i["state"] == "open"
                ]
                return json.dumps(open_)
            case ["issue", "create"]:
                number = len(self.issues) + 1
                self.issues[number] = {
                    "title": opts["--title"],
                    "body": opts["--body"],
                    "labels": set(),
                    "state": "open",
                }
                return f"https://github.com/{SLUG}/issues/{number}\n"
            case ["issue", "edit"]:
                self.issues[int(args[2])]["body"] = args[4]
                return ""
            case ["issue", "view"]:
                names = self.issues[int(args[2])]["labels"]
                return json.dumps({"labels": [{"name": n} for n in sorted(names)]})
            case ["label", "create"]:
                self.labels.add(args[2])
                return ""
        raise AssertionError(f"unexpected gh call {args}")


@pytest.fixture
def gh(monkeypatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(github, "_gh", fake)
    monkeypatch.setenv("GITHUB_REPOSITORY", SLUG)
    return fake


def rendered_post(root, post_id="2026-09-25-test", n=3, **kw):
    path = write_post(
        root, render_post_data(post_id, mode="prebuilt", slides=[], status="rendered", **kw)
    )
    for i in range(1, n + 1):
        make_jpeg(path.parent / "slides" / f"{i}.jpg")
    return path


def run(root, *args):
    return CliRunner().invoke(main, ["--root", str(root), *args])


# --- body -------------------------------------------------------------------


def test_body_has_pinned_slides_caption_and_schedule():
    post = Post.model_validate(render_post_data(caption="שלום ```x``` עולם"))
    body = approval.build_issue_body(post, SLUG, SHA, 2)
    for n in (1, 2):
        url = f"https://raw.githubusercontent.com/{SLUG}/{SHA}/queue/2026-09-25-test/slides/{n}.jpg"
        assert url in body
    assert "slides/3.jpg" not in body
    assert "2026-09-25 07:00 (Asia/Jerusalem)" in body
    assert "⏳ **Waiting for approval**" in body
    # Caption fenced with more backticks than it contains, so it renders verbatim.
    assert "````\nשלום ```x``` עולם\n````" in body


def test_body_shows_approved_state():
    post = Post.model_validate(render_post_data(approved=True))
    assert approval.build_issue_body(post, SLUG, SHA, 2).startswith("✅ **Approved**")


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Approve: 2026-09-25-manifesto", "2026-09-25-manifesto"),
        ("Approve: 2026-09-25-manifesto ", None),
        ("Approve: 2026-09-25-x; rm -rf /", None),
        ("Approve: ../../etc", None),
        ("Bug: 2026-09-25-manifesto", None),
    ],
)
def test_post_id_from_title(title, expected):
    assert approval.post_id_from_title(title) == expected


# --- open-issues ------------------------------------------------------------


def test_open_issues_creates_once_then_updates(repo, gh):
    rendered_post(repo)
    first = run(repo, "open-issues", "--sha", SHA, "2026-09-25-test")
    assert first.exit_code == 0, first.output
    assert "opened issue #1" in first.output
    assert gh.labels == {"approved"}
    issue = gh.issues[1]
    assert issue["title"] == "Approve: 2026-09-25-test"
    assert issue["body"].count("<img ") == 3

    second = run(repo, "open-issues", "--sha", "f" * 40, "2026-09-25-test")
    assert "updated issue #1" in second.output
    assert len(gh.issues) == 1
    assert "/" + "f" * 40 + "/" in gh.issues[1]["body"]


def test_open_issues_ignores_closed_issue_and_opens_fresh(repo, gh):
    rendered_post(repo)
    run(repo, "open-issues", "--sha", SHA)
    gh.issues[1]["state"] = "closed"
    result = run(repo, "open-issues", "--sha", SHA)
    assert "opened issue #2" in result.output


@pytest.mark.parametrize("state", ["queued", "publishing", "published", "failed"])
def test_open_issues_only_for_rendered_posts(repo, gh, state):
    write_post(repo, render_post_data(status=state))
    result = run(repo, "open-issues", "--sha", SHA)
    assert result.exit_code == 0
    assert f"status {state}, no approval issue" in result.output
    assert gh.issues == {}


# --- label sync -------------------------------------------------------------


def test_label_sync_approves_once(repo, gh):
    path = rendered_post(repo)
    run(repo, "open-issues", "--sha", SHA)

    unlabeled = run(repo, "approve-sync", "2026-09-25-test")
    assert "0 post(s) updated" in unlabeled.output
    assert load_post(path).approved is False

    gh.issues[1]["labels"].add("approved")
    labeled = run(repo, "approve-sync", "--from-issue-title", "Approve: 2026-09-25-test")
    assert labeled.exit_code == 0, labeled.output
    assert "approved via label" in labeled.output
    assert load_post(path).approved is True

    again = run(repo, "approve-sync", "2026-09-25-test")
    assert "0 post(s) updated" in again.output


def test_label_sync_preserves_everything_else(repo, gh):
    path = rendered_post(repo)
    before = load_post(path)
    run(repo, "open-issues", "--sha", SHA)
    gh.issues[1]["labels"].add("approved")
    run(repo, "approve-sync")
    after = load_post(path)
    assert after.model_copy(update={"approved": False}) == before


def test_other_labels_do_not_approve(repo, gh):
    path = rendered_post(repo)
    run(repo, "open-issues", "--sha", SHA)
    gh.issues[1]["labels"].add("looks-good")
    run(repo, "approve-sync")
    assert load_post(path).approved is False


def test_approve_sync_rejects_foreign_titles(repo, gh):
    result = run(repo, "approve-sync", "--from-issue-title", "🚨 DOXA failure")
    assert result.exit_code == 1
    assert "not an approval issue title" in result.output


def test_repo_slug_from_remote(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    class Done:
        stdout = "git@github.com:silverfox-il/doxa.git\n"

    monkeypatch.setattr(github.subprocess, "run", lambda *a, **k: Done())
    assert github.repo_slug() == "silverfox-il/doxa"
