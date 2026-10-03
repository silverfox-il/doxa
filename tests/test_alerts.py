"""Failure alerts: one rolling issue, a comment per new problem, no hourly spam."""

from __future__ import annotations

from click.testing import CliRunner

from doxa import alerts, github
from doxa.cli import main

TOKEN_ERR = (
    "✗ 2026-10-03-poison: GET /***/content_publishing_limit -> HTTP 401 code=190 "
    "subcode=0: Error validating access token"
)


class FakeIssues:
    def __init__(self, monkeypatch):
        self.issues: dict[int, dict] = {}
        monkeypatch.setattr(github, "find_open_issue", self.find)
        monkeypatch.setattr(github, "create_issue", self.create)
        monkeypatch.setattr(github, "issue_body", lambda n: self.issues[n]["body"])
        monkeypatch.setattr(github, "update_issue_body", self.update)
        monkeypatch.setattr(
            github, "comment_issue", lambda n, b: self.issues[n]["comments"].append(b)
        )

    def find(self, title):
        return next((n for n, i in self.issues.items() if i["title"] == title), None)

    def create(self, title, body):
        n = len(self.issues) + 1
        self.issues[n] = {"title": title, "body": body, "comments": []}
        return n

    def update(self, n, body):
        self.issues[n]["body"] = body


def test_first_failure_opens_issue_with_hint(monkeypatch):
    fake = FakeIssues(monkeypatch)
    assert alerts.report_failure("publish", TOKEN_ERR) == "opened"
    issue = fake.issues[1]
    assert issue["title"] == "🚨 DOXA failure"
    assert "IG_ACCESS_TOKEN" in issue["body"] and "code=190" in issue["body"]


def test_same_failure_only_bumps_counter(monkeypatch):
    fake = FakeIssues(monkeypatch)
    alerts.report_failure("publish", TOKEN_ERR)
    other_post = TOKEN_ERR.replace("2026-10-03-poison", "2026-10-03-nice-guy")
    assert alerts.report_failure("publish", other_post) == "bumped"
    assert alerts.report_failure("publish", TOKEN_ERR) == "bumped"
    assert fake.issues[1]["comments"] == []
    assert "Same failure 3 times" in fake.issues[1]["body"]


def test_new_failure_comments(monkeypatch):
    fake = FakeIssues(monkeypatch)
    alerts.report_failure("publish", TOKEN_ERR)
    assert alerts.report_failure("render", "✗ reel: ffmpeg failed") == "commented"
    assert len(fake.issues[1]["comments"]) == 1
    assert "ffmpeg failed" in fake.issues[1]["body"]


def test_summarize_keeps_error_lines():
    log = "doxa publish [LIVE]\npost: x\n  HEAD ok  url\n✗ x: boom\n"
    assert alerts.summarize(log) == "✗ x: boom"
    assert alerts.summarize("a\nb") == "a\nb"


def test_alert_cli_reads_log_file(monkeypatch, tmp_path):
    fake = FakeIssues(monkeypatch)
    log = tmp_path / "publish.log"
    log.write_text(f"doxa publish [LIVE]\n{TOKEN_ERR}\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["alert", "--step", "publish", "--log-file", str(log)])
    assert result.exit_code == 0, result.output
    assert "opened" in result.output
    assert "code=190" in fake.issues[1]["body"]
