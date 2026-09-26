"""Publisher (spec §5): at most one approved, due post per run.

Order of a real run:

1. Recover any post left in ``publishing`` by a crashed run: if a recent
   Instagram post has the same caption it is marked ``published``, otherwise
   ``failed-retryable``.
2. Pick the post (``--post-id`` or the oldest due one). It must be approved
   with a current ``approved_hash``, in ``rendered``/``failed-retryable``, and
   due in Asia/Jerusalem time.
3. Validate the JPEGs, build raw.githubusercontent.com URLs pinned to the
   checked-out commit, HEAD-check each (200 + ``image/jpeg``).
4. Check ``content_publishing_limit``; abort if the quota is used up.
5. Create child containers and the CAROUSEL container, poll until FINISHED.
6. Commit ``status: publishing`` (idempotency marker), then ``media_publish``.
7. Store ``ig_media_id``/``permalink``/``published_at``, close the approval
   issue with the permalink, regenerate STATUS.md, commit.

A dry run performs every read (selection, JPEG checks, HEAD checks, quota)
and logs what it would POST, but makes no POST to Meta, writes no file,
commits nothing and touches no issue.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests

from . import approval, github, slides, status
from .instagram import (
    API_VERSION,
    Client,
    InstagramError,
    InstagramRetryableError,
    QuotaExceededError,
    with_retry,
)
from .queue import (
    PUBLISHABLE_STATUSES,
    TZ,
    Post,
    Status,
    approval_is_current,
    dump_post,
    load_all,
    select_publishable,
    slide_files,
)

Log = Callable[[str], None]


class Committer(Protocol):
    def commit(self, paths: list[Path], message: str) -> None: ...


@dataclass
class GitCommitter:
    """Commit and push to ``main`` from a workflow checkout."""

    root: Path

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout

    def commit(self, paths: list[Path], message: str) -> None:
        self._git("add", "--", *(str(p) for p in paths))
        if not self._git("diff", "--cached", "--name-only").strip():
            return
        self._git("commit", "-m", message)
        self._git("pull", "--rebase", "--quiet", "origin", "main")
        self._git("push", "origin", "HEAD:main")


def head_check(url: str) -> tuple[int, str]:
    """HEAD a public image URL; return (status_code, content_type)."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=30)
    except requests.RequestException as e:
        return 0, type(e).__name__
    return resp.status_code, resp.headers.get("Content-Type", "")


def normalize_caption(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


@dataclass
class Publisher:
    root: Path
    client: Client
    slug: str
    sha: str
    committer: Committer
    log: Log
    now: dt.datetime = field(default_factory=lambda: dt.datetime.now(TZ))
    head: Callable[[str], tuple[int, str]] = head_check
    sleep: Callable[[float], None] = time.sleep
    poll_s: float = 15.0

    # --- helpers --------------------------------------------------------------

    @property
    def queue_dir(self) -> Path:
        return self.root / "queue"

    def _save(self, post: Post, path: Path, message: str, quota: str | None = None) -> None:
        dump_post(post, path)
        status.write_status(self.root, self.now, quota=quota)
        self.committer.commit([path, self.root / "STATUS.md"], message)

    def _retry(self, what: str, fn):
        def note(attempt: int, e: Exception) -> None:
            self.log(f"  retry {attempt} for {what}: {e}")

        return with_retry(fn, sleep=self.sleep, on_retry=note)

    def blockers(self, path: Path, post: Post) -> list[str]:
        """Reasons this post may not be published right now (empty = eligible)."""
        out = []
        if not post.approved:
            out.append("not approved")
        elif not approval_is_current(post, path.parent):
            out.append("approval is stale (content changed since approval)")
        if post.status not in PUBLISHABLE_STATUSES:
            out.append(f"status is {post.status.value}")
        if not post.is_due(self.now):
            out.append(f"not due until {post.publish_at} Asia/Jerusalem")
        return out

    def image_urls(self, post: Post, path: Path) -> list[str]:
        n = len(slide_files(path.parent / "slides"))
        return [github.raw_url(self.slug, self.sha, post.id, i) for i in range(1, n + 1)]

    def check_urls(self, urls: list[str]) -> None:
        """Every URL must answer 200 image/jpeg; raw.githubusercontent can lag a push."""
        for url in urls:
            for attempt in range(3):
                code, ctype = self.head(url)
                if code == 200 and ctype.split(";")[0].strip() == "image/jpeg":
                    break
                if attempt < 2:
                    self.sleep(10 * (attempt + 1))
            else:
                raise InstagramRetryableError(f"HEAD {url} -> {code} {ctype}")
            self.log(f"  HEAD ok  {url}")

    # --- recovery -------------------------------------------------------------

    def recover(self, dry_run: bool) -> None:
        """Resolve posts a crashed run left in ``publishing``."""
        stuck = [
            (p, post) for p, post in load_all(self.queue_dir) if post.status == Status.publishing
        ]
        if not stuck:
            return
        recent = self._retry("recent media", lambda: self.client.recent_media())
        by_caption = {normalize_caption(m.get("caption") or ""): m for m in recent}
        for path, post in stuck:
            match = by_caption.get(normalize_caption(post.caption))
            if match:
                self.log(f"recover {post.id}: already on Instagram as {match.get('permalink')}")
                if dry_run:
                    continue
                self._mark_published(post, path, str(match["id"]), match)
            else:
                self.log(f"recover {post.id}: not found on Instagram -> failed-retryable")
                if dry_run:
                    continue
                post.status = Status.failed_retryable
                post.error = "previous publish run was interrupted before media_publish finished"
                self._save(post, path, f"publish: {post.id} interrupted, will retry")

    def _mark_published(self, post: Post, path: Path, media_id: str, media: dict) -> None:
        post.status = Status.published
        post.ig_media_id = media_id
        post.permalink = media.get("permalink")
        post.published_at = media.get("timestamp") or self.now.isoformat(timespec="seconds")
        post.error = None
        self._save(post, path, f"publish: {post.id} published")
        number = github.find_open_issue(approval.issue_title(post.id))
        if number is not None:
            github.close_issue(number, f"Published: {post.permalink}")

    # --- main -----------------------------------------------------------------

    def run(self, *, dry_run: bool, post_id: str | None = None) -> int:
        """Returns a process exit code (0 = ok or nothing to do)."""
        mode = "DRY RUN — no POST to Meta, no commits" if dry_run else "LIVE"
        self.log(f"doxa publish [{mode}] at {self.now:%Y-%m-%d %H:%M %Z} commit {self.sha[:7]}")
        self.recover(dry_run)

        posts = load_all(self.queue_dir)
        if post_id:
            chosen = next(((p, post) for p, post in posts if post.id == post_id), None)
            if chosen is None:
                self.log(f"✗ no post with id {post_id}")
                return 1
        else:
            chosen = select_publishable(posts, self.now)
            if chosen is None:
                self.log("nothing due and approved — done")
                return 0
        path, post = chosen
        self.log(f"post: {post.id} (publish_at {post.publish_at}, status {post.status.value})")

        blockers = self.blockers(path, post)
        if blockers:
            for b in blockers:
                self.log(f"  BLOCKED: {b}")
            if not dry_run:
                self.log("✗ not publishing")
                return 1
            self.log("  (dry run continues so you can preview the request)")

        problems = slides.validate_slides(path.parent / "slides")
        if problems:
            for p in problems:
                self.log(f"✗ {p}")
            return self._fail(post, path, "; ".join(problems), dry_run, retryable=False)

        urls = self.image_urls(post, path)
        try:
            self.check_urls(urls)
            quota = self._retry("publishing limit", self.client.publishing_quota)
        except InstagramError as e:
            return self._fail(post, path, str(e), dry_run, retryable=True)
        self.log(f"  quota: {quota}")
        if quota.exhausted:
            self.log("✗ publishing quota exhausted — try again later")
            return 1

        if dry_run:
            self._log_plan(post, urls, blockers)
            return 0
        return self._publish(post, path, urls, str(quota))

    def _log_plan(self, post: Post, urls: list[str], blockers: list[str]) -> None:
        """Log the exact JSON bodies a live run would POST (ids are placeholders)."""
        user = self.client.ig_user_id
        base = f"https://graph.instagram.com/{API_VERSION}/{user}"

        def body(b: dict) -> str:
            return json.dumps(b, ensure_ascii=False)

        for i, url in enumerate(urls, start=1):
            self.log(f"  would POST {base}/media  (child {i}/{len(urls)})")
            self.log(f"    {body(Client.carousel_item_body(url))}")
        children = [f"<child-{i}-id>" for i in range(1, len(urls) + 1)]
        self.log(f"  would POST {base}/media  (carousel)")
        self.log(f"    {body(Client.carousel_body(children, post.caption))}")
        lines = post.caption.rstrip("\n").splitlines()
        self.log(f"  caption: {len(post.caption)} chars, {len(lines)} lines:")
        for line in lines:
            self.log(f"    | {line}")
        self.log(f"  would poll GET /<carousel-id>?fields=status_code every {self.poll_s:.0f}s")
        self.log("  would commit status: publishing, then:")
        self.log(f"  would POST {base}/media_publish")
        self.log(f"    {body(Client.publish_body('<carousel-id>'))}")
        if blockers:
            self.log(
                f"✓ dry run complete — nothing was sent (a live run is BLOCKED: "
                f"{'; '.join(blockers)})"
            )
        else:
            self.log("✓ dry run complete — nothing was sent (a live run would publish)")

    def _publish(self, post: Post, path: Path, urls: list[str], quota: str) -> int:
        c = self.client
        try:
            children = []
            for i, url in enumerate(urls, start=1):
                cid = self._retry(f"child {i}", lambda u=url: c.create_carousel_item(u))
                self.log(f"  child container {i}/{len(urls)}: {cid}")
                children.append(cid)
            parent = self._retry(
                "carousel", lambda: c.create_carousel_container(children, post.caption)
            )
            self.log(f"  carousel container: {parent}")
            c.wait_finished(parent, poll_s=self.poll_s, sleep=self.sleep)
            self.log("  container FINISHED")
        except InstagramError as e:
            retryable = isinstance(e, InstagramRetryableError | QuotaExceededError)
            return self._fail(post, path, str(e), False, retryable=retryable)

        # Idempotency marker: if we crash after this, the next run checks
        # Instagram for this caption before trying again.
        post.status = Status.publishing
        post.error = None
        self._save(post, path, f"publish: {post.id} publishing", quota)

        try:
            media_id = c.publish(parent)
        except InstagramRetryableError as e:
            # Ambiguous: it may have gone through. Leave `publishing` for recovery.
            post.error = f"media_publish uncertain: {e}"
            self._save(post, path, f"publish: {post.id} outcome unknown", quota)
            self.log(f"✗ {post.error} — next run checks Instagram before retrying")
            return 1
        except InstagramError as e:
            return self._fail(
                post, path, str(e), False, retryable=isinstance(e, QuotaExceededError)
            )

        self.log(f"  published media id {media_id}")
        try:
            media = self._retry("permalink", lambda: c.get_media(media_id))
        except InstagramError as e:
            self.log(f"  could not fetch permalink yet: {e}")
            media = {}
        self._mark_published(post, path, media_id, media)
        self.log(f"✓ published {post.id}: {post.permalink}")
        return 0

    def _fail(self, post: Post, path: Path, error: str, dry_run: bool, *, retryable: bool) -> int:
        state = Status.failed_retryable if retryable else Status.failed
        self.log(f"✗ {post.id}: {error}")
        if dry_run:
            self.log(f"  (a live run would set status: {state.value})")
            return 1
        post.status = state
        post.error = error
        self._save(post, path, f"publish: {post.id} {state.value}")
        return 1
