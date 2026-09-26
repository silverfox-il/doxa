"""Publisher (spec §5) with a fake Instagram client, fake git and fake HEAD checks."""

from __future__ import annotations

import datetime as dt

import pytest
from click.testing import CliRunner

from doxa import github
from doxa.cli import main
from doxa.instagram import (
    InstagramError,
    InstagramRetryableError,
    Quota,
    QuotaExceededError,
)
from doxa.publish import Publisher
from doxa.queue import TZ, Status, content_hash, dump_post, load_post

from .conftest import make_jpeg, render_post_data, write_post

SHA = "abc1234def5678abc1234def5678abc1234def56"
SLUG = "silverfox-il/doxa"
NOW = dt.datetime(2026, 9, 25, 9, 0, tzinfo=TZ)
POSTS = ("create_carousel_item", "create_carousel_container", "publish")


class FakeClient:
    ig_user_id = "17841400000000000"

    def __init__(self, repo):
        self.repo = repo
        self.calls: list[str] = []
        self.quota = Quota(usage=1, total=100)
        self.recent: list[dict] = []
        self.fail: dict[str, list[Exception]] = {}
        self.status_at_publish = None

    def _maybe_fail(self, name):
        queue = self.fail.get(name)
        if queue:
            raise queue.pop(0)

    def publishing_quota(self):
        self.calls.append("quota")
        self._maybe_fail("quota")
        return self.quota

    def recent_media(self):
        self.calls.append("recent_media")
        return self.recent

    def create_carousel_item(self, url):
        self.calls.append("create_carousel_item")
        self._maybe_fail("create_carousel_item")
        return f"child-{url.rsplit('/', 1)[-1]}"

    def create_carousel_container(self, children, caption):
        self.calls.append("create_carousel_container")
        self._maybe_fail("create_carousel_container")
        assert children == ["child-1.jpg", "child-2.jpg", "child-3.jpg"]
        return "parent"

    def wait_finished(self, container_id, **kw):
        self.calls.append("wait_finished")
        self._maybe_fail("wait_finished")

    def publish(self, creation_id):
        self.calls.append("publish")
        # What is committed on disk at the moment media_publish is called.
        self.status_at_publish = load_post(
            self.repo / "queue" / "2026-09-25-post" / "post.yaml"
        ).status
        self._maybe_fail("publish")
        return "media-1"

    def get_media(self, media_id):
        self.calls.append("get_media")
        return {
            "id": media_id,
            "permalink": "https://www.instagram.com/p/ABC/",
            "timestamp": "2026-09-25T06:00:00+0000",
        }


class FakeCommitter:
    def __init__(self):
        self.commits: list[str] = []

    def commit(self, paths, message):
        self.commits.append(message)


@pytest.fixture
def gh_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(github, "find_open_issue", lambda title: 7)
    monkeypatch.setattr(github, "close_issue", lambda n, c: calls.append((n, c)))
    return calls


def approved_post(repo, post_id="2026-09-25-post", n=3, approved=True, **kw):
    kw.setdefault("publish_at", "2026-09-25 07:00")
    kw.setdefault("status", "rendered")
    path = write_post(repo, render_post_data(post_id, mode="prebuilt", slides=[], **kw))
    for i in range(1, n + 1):
        make_jpeg(path.parent / "slides" / f"{i}.jpg", color=(i * 20, 30, 40))
    post = load_post(path)
    if approved:
        post.approved = True
        post.approved_hash = content_hash(post, path.parent)
        dump_post(post, path)
    return path


def publisher(repo, head=None):
    logs = []
    client = FakeClient(repo)
    committer = FakeCommitter()
    p = Publisher(
        root=repo,
        client=client,
        slug=SLUG,
        sha=SHA,
        committer=committer,
        log=logs.append,
        now=NOW,
        head=head or (lambda url: (200, "image/jpeg")),
        sleep=lambda s: None,
    )
    return p, client, committer, logs


def posts_sent(client):
    return [c for c in client.calls if c in POSTS]


# --- dry run --------------------------------------------------------------------


def test_dry_run_reads_everything_sends_nothing(repo, gh_calls):
    path = approved_post(repo)
    before = path.read_text(encoding="utf-8")
    heads = []
    p, client, committer, logs = publisher(
        repo, head=lambda u: heads.append(u) or (200, "image/jpeg")
    )

    assert p.run(dry_run=True) == 0
    assert posts_sent(client) == []
    assert "quota" in client.calls
    assert committer.commits == [] and gh_calls == []
    assert path.read_text(encoding="utf-8") == before
    assert not (repo / "STATUS.md").exists()
    assert heads == [
        f"https://raw.githubusercontent.com/{SLUG}/{SHA}/queue/2026-09-25-post/slides/{i}.jpg"
        for i in (1, 2, 3)
    ]
    text = "\n".join(logs)
    assert "DRY RUN" in text
    base = "https://graph.instagram.com/v26.0/17841400000000000"
    assert text.count(f"would POST {base}/media  (child") == 3
    url1 = f"https://raw.githubusercontent.com/{SLUG}/{SHA}/queue/2026-09-25-post/slides/1.jpg"
    assert f'{{"image_url": "{url1}", "is_carousel_item": true}}' in text
    assert (
        '{"media_type": "CAROUSEL", "children": "<child-1-id>,<child-2-id>,<child-3-id>", '
        '"caption": "שורה ראשונה\\nשורה שנייה #סילברפוקס"}'
    ) in text
    assert f"would POST {base}/media_publish" in text
    assert '{"creation_id": "<carousel-id>"}' in text
    assert "a live run would publish" in text


def test_dry_run_on_blocked_post_previews_and_says_why(repo, gh_calls):
    approved_post(repo, approved=False, publish_at="2026-12-31 07:00")
    p, client, committer, logs = publisher(repo)
    assert p.run(dry_run=True, post_id="2026-09-25-post") == 0
    text = "\n".join(logs)
    assert "BLOCKED: not approved" in text
    assert "BLOCKED: not due until 2026-12-31 07:00" in text
    assert "a live run is BLOCKED" in text
    assert posts_sent(client) == [] and committer.commits == []


# --- live: happy path -------------------------------------------------------------


def test_live_publishes_in_order_with_idempotency_marker(repo, gh_calls):
    path = approved_post(repo)
    p, client, committer, logs = publisher(repo)

    assert p.run(dry_run=False) == 0
    assert client.calls == [
        "quota",
        "create_carousel_item",
        "create_carousel_item",
        "create_carousel_item",
        "create_carousel_container",
        "wait_finished",
        "publish",
        "get_media",
    ]
    # `publishing` was committed before media_publish was called.
    assert client.status_at_publish == Status.publishing
    assert committer.commits == [
        "publish: 2026-09-25-post publishing",
        "publish: 2026-09-25-post published",
    ]
    post = load_post(path)
    assert post.status == Status.published
    assert post.ig_media_id == "media-1"
    assert post.permalink == "https://www.instagram.com/p/ABC/"
    assert post.published_at == "2026-09-25T06:00:00+0000"
    assert gh_calls == [(7, "Published: https://www.instagram.com/p/ABC/")]
    assert "published" in (repo / "STATUS.md").read_text(encoding="utf-8")


def test_at_most_one_post_per_run_oldest_first(repo, gh_calls):
    approved_post(repo, "2026-09-25-post")
    newer = approved_post(repo, "2026-09-25-later", publish_at="2026-09-25 08:00")
    p, client, _, _ = publisher(repo)
    assert p.run(dry_run=False) == 0
    assert client.calls.count("publish") == 1
    assert load_post(newer).status == Status.rendered


def test_published_post_is_never_published_again(repo, gh_calls):
    approved_post(repo)
    p, client, _, _ = publisher(repo)
    p.run(dry_run=False)
    p2, client2, committer2, logs2 = publisher(repo)
    assert p2.run(dry_run=False) == 0
    assert posts_sent(client2) == [] and committer2.commits == []
    assert "nothing due" in logs2[-1]


# --- live: refusals -------------------------------------------------------------


@pytest.mark.parametrize(
    "setup,reason",
    [
        (lambda repo: approved_post(repo, approved=False), "not approved"),
        (lambda repo: approved_post(repo, publish_at="2026-09-25 10:00"), "not due"),
    ],
)
def test_live_refuses_ineligible_post_id(repo, gh_calls, setup, reason):
    setup(repo)
    p, client, committer, logs = publisher(repo)
    assert p.run(dry_run=False, post_id="2026-09-25-post") == 1
    assert any(reason in line for line in logs)
    assert posts_sent(client) == [] and committer.commits == []


def test_edit_after_approval_blocks_publish(repo, gh_calls):
    path = approved_post(repo)
    post = load_post(path)
    post.caption = "שונה אחרי האישור"
    dump_post(post, path)  # no re-render yet, so approved stays true but hash is stale
    p, client, committer, logs = publisher(repo)
    assert p.run(dry_run=False) == 0  # cron: nothing eligible
    assert posts_sent(client) == []
    assert p.run(dry_run=False, post_id="2026-09-25-post") == 1
    assert any("approval is stale" in line for line in logs)


def test_quota_exhausted_aborts_without_state_change(repo, gh_calls):
    path = approved_post(repo)
    before = path.read_text(encoding="utf-8")
    p, client, committer, logs = publisher(repo)
    client.quota = Quota(usage=100, total=100)
    assert p.run(dry_run=False) == 1
    assert posts_sent(client) == [] and committer.commits == []
    assert path.read_text(encoding="utf-8") == before
    assert "quota exhausted" in logs[-1]


def test_head_check_failure_marks_retryable_without_calling_meta(repo, gh_calls):
    path = approved_post(repo)
    p, client, committer, logs = publisher(repo, head=lambda u: (404, "text/plain"))
    assert p.run(dry_run=False) == 1
    assert client.calls == []  # not even the quota check
    post = load_post(path)
    assert post.status == Status.failed_retryable
    assert "HEAD" in post.error and "404" in post.error


# --- live: errors and retries ------------------------------------------------------


def test_transient_container_error_is_retried(repo, gh_calls):
    path = approved_post(repo)
    p, client, _, logs = publisher(repo)
    client.fail["create_carousel_item"] = [
        InstagramRetryableError("503"),
        InstagramRetryableError("503"),
    ]
    assert p.run(dry_run=False) == 0
    assert load_post(path).status == Status.published
    assert sum("retry" in line for line in logs) == 2


def test_persistent_transient_error_becomes_failed_retryable(repo, gh_calls):
    path = approved_post(repo)
    p, client, committer, _ = publisher(repo)
    client.fail["create_carousel_container"] = [InstagramRetryableError("503")] * 3
    assert p.run(dry_run=False) == 1
    post = load_post(path)
    assert post.status == Status.failed_retryable and "503" in post.error
    assert "publish" not in client.calls
    assert committer.commits == ["publish: 2026-09-25-post failed-retryable"]


def test_fatal_error_marks_failed(repo, gh_calls):
    path = approved_post(repo)
    p, client, _, _ = publisher(repo)
    client.fail["wait_finished"] = [InstagramError("container parent status ERROR")]
    assert p.run(dry_run=False) == 1
    post = load_post(path)
    assert post.status == Status.failed and "ERROR" in post.error


def test_quota_error_at_publish_is_retryable(repo, gh_calls):
    path = approved_post(repo)
    p, client, _, _ = publisher(repo)
    client.fail["publish"] = [QuotaExceededError("code=9")]
    assert p.run(dry_run=False) == 1
    assert load_post(path).status == Status.failed_retryable


def test_ambiguous_publish_failure_is_not_retried_blindly(repo, gh_calls):
    path = approved_post(repo)
    p, client, committer, _ = publisher(repo)
    client.fail["publish"] = [InstagramRetryableError("network error: ReadTimeout")]
    assert p.run(dry_run=False) == 1
    assert client.calls.count("publish") == 1  # media_publish is never auto-retried
    post = load_post(path)
    assert post.status == Status.publishing
    assert "uncertain" in post.error


# --- crash recovery -----------------------------------------------------------------


def test_recovery_finds_post_already_on_instagram(repo, gh_calls):
    path = approved_post(repo, status="publishing")
    p, client, committer, logs = publisher(repo)
    post = load_post(path)
    client.recent = [
        {"id": "other", "caption": "something else"},
        {
            "id": "media-7",
            "caption": post.caption.strip() + "\n",
            "permalink": "https://www.instagram.com/p/OLD/",
            "timestamp": "2026-09-25T04:00:00+0000",
        },
    ]
    assert p.run(dry_run=False) == 0
    post = load_post(path)
    assert post.status == Status.published and post.ig_media_id == "media-7"
    assert posts_sent(client) == []  # never published twice
    assert gh_calls == [(7, "Published: https://www.instagram.com/p/OLD/")]


def test_recovery_retries_when_not_on_instagram(repo, gh_calls):
    path = approved_post(repo, status="publishing")
    p, client, committer, logs = publisher(repo)
    client.recent = [{"id": "other", "caption": "something else"}]
    assert p.run(dry_run=False) == 0
    assert committer.commits[0] == "publish: 2026-09-25-post interrupted, will retry"
    assert load_post(path).status == Status.published  # retried in the same run
    assert client.calls.count("publish") == 1


def test_dry_run_recovery_only_reports(repo, gh_calls):
    path = approved_post(repo, status="publishing")
    before = path.read_text(encoding="utf-8")
    p, client, committer, logs = publisher(repo)
    p.run(dry_run=True)
    assert path.read_text(encoding="utf-8") == before and committer.commits == []
    assert any("recover 2026-09-25-post" in line for line in logs)


# --- CLI ---------------------------------------------------------------------------


@pytest.fixture
def ig_env(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "IGAA-secret-token-value")
    monkeypatch.setenv("IG_USER_ID", "17841400000000000")


def _fake_account(monkeypatch, user_id="17841400000000000", username="the_silver_fox_men"):
    from doxa.instagram import Client

    monkeypatch.setattr(Client, "me", lambda self: {"user_id": user_id, "username": username})
    monkeypatch.setattr(Client, "publishing_quota", lambda self: Quota(usage=2, total=100))


def test_check_prints_only_username_user_id_quota(repo, ig_env, monkeypatch):
    _fake_account(monkeypatch)
    result = CliRunner().invoke(
        main, ["--root", str(repo), "check", "--expect-username", "the_silver_fox_men"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "username: the_silver_fox_men",
        "user_id:  17841400000000000",
        "quota:    2/100 in the last 24h",
    ]
    assert "IGAA" not in result.output


@pytest.mark.parametrize(
    "kw,msg",
    [
        ({"user_id": "999"}, "IG_USER_ID does not match"),
        ({"username": "someone_else"}, "expected username the_silver_fox_men"),
    ],
)
def test_check_fails_on_wrong_account(repo, ig_env, monkeypatch, kw, msg):
    _fake_account(monkeypatch, **kw)
    result = CliRunner().invoke(
        main, ["--root", str(repo), "check", "--expect-username", "the_silver_fox_men"]
    )
    assert result.exit_code == 1
    assert msg in result.output


def test_missing_secrets_named_not_shown(repo, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("IG_USER_ID", "17841400000000000")
    result = CliRunner().invoke(main, ["--root", str(repo), "check"])
    assert result.exit_code == 1
    assert "IG_ACCESS_TOKEN not set" in result.output
    assert "17841400000000000" not in result.output


def test_publish_cli_defaults_to_dry_run(repo, ig_env, monkeypatch):
    seen = {}

    def fake_run(self, *, dry_run, post_id=None):
        seen.update(dry_run=dry_run, post_id=post_id, sha=self.sha)
        return 0

    monkeypatch.setattr(Publisher, "run", fake_run)
    monkeypatch.setenv("GITHUB_REPOSITORY", SLUG)
    result = CliRunner().invoke(main, ["--root", str(repo), "publish", "--sha", SHA])
    assert result.exit_code == 0, result.output
    assert seen == {"dry_run": True, "post_id": None, "sha": SHA}
    CliRunner().invoke(
        main, ["--root", str(repo), "publish", "--sha", SHA, "--live", "--post-id", "2026-09-25-x"]
    )
    assert seen["dry_run"] is False and seen["post_id"] == "2026-09-25-x"


def test_publish_cli_rejects_bad_post_id(repo, ig_env):
    result = CliRunner().invoke(main, ["--root", str(repo), "publish", "--post-id", "../x"])
    assert result.exit_code == 1 and "not a post id" in result.output
