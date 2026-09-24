"""Approval-issue flow (spec §4) against an in-memory fake of the `gh` CLI."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from doxa import approval, github
from doxa.cli import main
from doxa.queue import Post, approval_is_current, content_hash, dump_post, load_post

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
                    "comments": [],
                    "state": "open",
                }
                return f"https://github.com/{SLUG}/issues/{number}\n"
            case ["issue", "edit"] if args[3] == "--remove-label":
                self.issues[int(args[2])]["labels"].discard(args[4])
                return ""
            case ["issue", "edit"]:
                self.issues[int(args[2])]["body"] = args[4]
                return ""
            case ["issue", "view"]:
                issue = self.issues[int(args[2])]
                if args[-1] == "body":
                    return json.dumps({"body": issue["body"]})
                return json.dumps({"labels": [{"name": n} for n in sorted(issue["labels"])]})
            case ["issue", "comment"]:
                self.issues[int(args[2])]["comments"].append(args[4])
                return ""
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


def test_body_has_pinned_slides_caption_and_schedule(tmp_path):
    post = Post.model_validate(render_post_data(caption="שלום ```x``` עולם"))
    body = approval.build_issue_body(post, tmp_path, SLUG, SHA, 2)
    for n in (1, 2):
        url = f"https://raw.githubusercontent.com/{SLUG}/{SHA}/queue/2026-09-25-test/slides/{n}.jpg"
        assert url in body
    assert "slides/3.jpg" not in body
    assert "2026-09-25 07:00 (Asia/Jerusalem)" in body
    assert "⏳ **Waiting for approval**" in body
    # Caption fenced with more backticks than it contains, so it renders verbatim.
    assert "````\nשלום ```x``` עולם\n````" in body


def test_body_shows_approved_and_stale_states(tmp_path):
    post = Post.model_validate(render_post_data(approved=True))
    post.approved_hash = content_hash(post, tmp_path)
    assert approval.build_issue_body(post, tmp_path, SLUG, SHA, 2).startswith("✅ **Approved**")
    post.caption = "שונה"
    stale = approval.build_issue_body(post, tmp_path, SLUG, SHA, 2)
    assert stale.startswith("⚠️ **Approval is stale**")


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
    assert after.approved_hash == content_hash(after, path.parent)
    assert approval_is_current(after, path.parent)
    assert after.model_copy(update={"approved": False, "approved_hash": None}) == before


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


# --- approval reset ---------------------------------------------------------


def _approve_via_label(repo, gh, path):
    run(repo, "open-issues", "--sha", SHA)
    gh.issues[1]["labels"].add("approved")
    run(repo, "approve-sync")
    run(repo, "open-issues", "--sha", SHA)
    assert gh.issues[1]["body"].startswith("✅ **Approved**")
    assert approval_is_current(load_post(path), path.parent)


def test_edit_after_label_approval_resets_and_comments(repo, gh):
    path = rendered_post(repo)
    _approve_via_label(repo, gh, path)

    # Owner edits the caption after approving, then pushes -> render.yml.
    post = load_post(path)
    post.caption = "כיתוב חדש אחרי האישור"
    dump_post(post, path)
    rendered = run(repo, "render", "2026-09-25-test")
    assert "approval reset" in rendered.output
    after = load_post(path)
    assert after.approved is False and after.approved_hash is None

    run(repo, "open-issues", "--sha", SHA)
    assert gh.issues[1]["body"].startswith("⏳ **Waiting for approval**")
    assert gh.issues[1]["comments"] == [approval.RESET_COMMENT]
    assert "approved" not in gh.issues[1]["labels"]

    # A label sync now finds no label, so nothing is re-approved by accident.
    assert "0 post(s) updated" in run(repo, "approve-sync").output
    assert load_post(path).approved is False

    # Refreshing again does not repeat the comment.
    run(repo, "open-issues", "--sha", SHA)
    assert len(gh.issues[1]["comments"]) == 1


def test_relabel_after_reset_approves_new_content(repo, gh):
    path = rendered_post(repo)
    _approve_via_label(repo, gh, path)
    make_jpeg(path.parent / "slides" / "2.jpg", color=(200, 10, 10))  # replaced slide
    run(repo, "render")
    run(repo, "open-issues", "--sha", SHA)
    assert load_post(path).approved is False
    gh.issues[1]["labels"].add("approved")  # owner reviews and labels again
    result = run(repo, "approve-sync", "2026-09-25-test")
    assert "approved via label" in result.output
    assert approval_is_current(load_post(path), path.parent)


def test_unchanged_rerender_keeps_approval(repo, gh):
    path = rendered_post(repo)
    _approve_via_label(repo, gh, path)
    before = path.read_text(encoding="utf-8")
    result = run(repo, "render")
    assert result.exit_code == 0
    assert path.read_text(encoding="utf-8") == before


def test_manual_yaml_approval_is_stamped_on_render(repo):
    path = rendered_post(repo, approved=True)
    assert load_post(path).approved_hash is None
    result = run(repo, "render")
    assert "content hash recorded" in result.output
    assert approval_is_current(load_post(path), path.parent)


def test_unapproved_post_drops_leftover_hash(repo):
    path = rendered_post(repo, approved_hash="sha256:old")
    run(repo, "render")
    assert load_post(path).approved_hash is None


@pytest.mark.parametrize(
    "outcome,kw",
    [
        ("stamped", {"approved": True}),
        ("reset", {"approved": True, "approved_hash": "sha256:old"}),
        ("cleared", {"approved": False, "approved_hash": "sha256:old"}),
        (None, {"approved": False}),
    ],
)
def test_reconcile_outcomes(tmp_path, outcome, kw):
    post = Post.model_validate(render_post_data(**kw))
    assert approval.reconcile(post, tmp_path) == outcome
    assert (post.approved_hash is not None) == post.approved
