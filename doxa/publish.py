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
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests

from . import approval, github, pacing, reel, slides, status
from .instagram import (
    API_VERSION,
    ActionBlockedError,
    Client,
    InstagramError,
    InstagramRetryableError,
    QuotaExceededError,
    with_retry,
)
from .queue import (
    PUBLISHABLE_STATUSES,
    TZ,
    Mode,
    Post,
    Status,
    approval_is_current,
    dump_post,
    load_all,
    slide_files,
)
from .story import story_files

# Video containers take longer to process than images.
REEL_PROCESS_TIMEOUT_S = 600.0

Log = Callable[[str], None]


def last_published_mode(posts: list[tuple[Path, Post]]) -> Mode | None:
    """Kind (reel or carousel) of the post that went live most recently."""
    live = [post for _, post in posts if post.published_at]
    return max(live, key=lambda post: post.published_at).mode if live else None


def backlog_order(due: list[tuple[Path, Post]], last_mode: Mode | None) -> list[tuple[Path, Post]]:
    """Order due posts so reels and carousels alternate (owner: 2 of each a day).

    When a backlog builds up, the next post is of the other kind than the last one
    published; with nothing published yet, a reel goes first (reels reach
    non-followers). Within each kind, oldest first. A post marked ``urgent`` goes
    before all of them.
    """
    prefer_reel = last_mode != Mode.reel
    return sorted(
        due,
        key=lambda pp: (
            not pp[1].urgent,
            (pp[1].mode == Mode.reel) != prefer_reel,
            pp[1].publish_at_dt,
        ),
    )


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

    def sync(self) -> None:
        """Pull the newest main before deciding what to publish.

        Another workflow (render, approve, a previous publish run) may have pushed
        since this checkout; acting on a stale queue could pick a post that was
        already published, and the later push would conflict.
        """
        self._git("pull", "--rebase", "--quiet", "origin", "main")

    def commit(self, paths: list[Path], message: str) -> None:
        self._git("add", "--", *(str(p) for p in paths))
        if not self._git("diff", "--cached", "--name-only").strip():
            return
        self._git("commit", "-m", message)
        self._git("pull", "--rebase", "--quiet", "origin", "main")
        self._git("push", "origin", "HEAD:main")


def is_mp4(url: str) -> bool:
    """True when the first bytes at ``url`` are an MP4 header (``ftyp`` box)."""
    try:
        resp = requests.get(url, headers={"Range": "bytes=0-15"}, timeout=30)
    except requests.RequestException:
        return False
    return resp.status_code in (200, 206) and resp.content[4:8] == b"ftyp"


def head_check(url: str) -> tuple[int, str]:
    """HEAD a public image URL; return (status_code, content_type)."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=30)
    except requests.RequestException as e:
        return 0, type(e).__name__
    return resp.status_code, resp.headers.get("Content-Type", "")


RLM = "\u200f"  # invisible right-to-left mark
_HEB = re.compile("[\u05d0-\u05ea]")
_LATIN = re.compile("[A-Za-z]")


def rtl_caption(text: str) -> str:
    """The caption as sent to Instagram: every Hebrew line reads right to left.

    Instagram picks each line's direction from its first strong letter, so a line
    that opens with a masked word ("Zונות ...") would flip to left-to-right and
    look reversed. An invisible RLM at the start of such a line keeps it RTL.
    """
    out = []
    for line in text.split("\n"):
        first = next((ch for ch in line if _HEB.match(ch) or _LATIN.match(ch)), "")
        if first and _LATIN.match(first) and _HEB.search(line):
            line = RLM + line
        out.append(line)
    return "\n".join(out)


def normalize_caption(text: str) -> str:
    return text.replace("\r\n", "\n").replace(RLM, "").strip()


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
    sniff_mp4: Callable[[str], bool] = is_mp4
    pacing: pacing.Pacing = field(default_factory=pacing.Pacing)
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
        if post.mode == Mode.reel and post.reel is None:
            out.append("reel post without a reel: block")
        if not post.approved:
            out.append("not approved")
        elif not approval_is_current(post, path.parent):
            out.append("approval is stale (content changed since approval)")
        if post.status not in PUBLISHABLE_STATUSES:
            out.append(f"status is {post.status.value}")
        if not post.is_due(self.now):
            out.append(f"not due until {post.publish_at} Asia/Jerusalem")
        until = approval.auto_veto_until(post)
        if until is not None and self.now < until:
            out.append(f"auto-approved: owner veto window open until {until:%Y-%m-%d %H:%M}")
        out += self.hold_blockers(post)
        return out

    def hold_blockers(self, post: Post) -> list[str]:
        """The owner's `hold` label on the approval issue vetoes publishing.

        Fails closed: if the label cannot be checked, the post does not publish.
        """
        try:
            number = github.find_open_issue(approval.issue_title(post.id))
            if number is not None and approval.HOLD_LABEL in github.issue_labels(number):
                return [f"on hold (label `{approval.HOLD_LABEL}` on issue #{number})"]
        except Exception as e:  # noqa: BLE001 — any gh failure must block, not publish
            return [f"cannot check the hold label: {type(e).__name__}"]
        return []

    def pick(self, posts: list[tuple[Path, Post]]) -> tuple[Path, Post] | None:
        """Oldest due, approved post that nothing blocks; logs every one skipped."""
        due = [
            (p, post)
            for p, post in posts
            if post.approved and post.status in PUBLISHABLE_STATUSES and post.is_due(self.now)
        ]
        due = backlog_order(due, last_published_mode(posts))
        for path, post in due:
            blockers = self.blockers(path, post)
            if not blockers:
                return path, post
            self.log(f"skip {post.id}: {'; '.join(blockers)}")
        return None

    def image_urls(self, post: Post, path: Path) -> list[str]:
        if post.mode == Mode.reel:
            return [github.raw_file_url(self.slug, self.sha, post.id, reel.VIDEO_NAME)]
        n = len(slide_files(path.parent / "slides"))
        return [github.raw_url(self.slug, self.sha, post.id, i) for i in range(1, n + 1)]

    def story_urls(self, post: Post, path: Path) -> list[str]:
        """What to share as stories, in order (see :mod:`doxa.story`)."""
        return [
            github.raw_file_url(self.slug, self.sha, post.id, name)
            for name in story_files(post, path.parent)
        ]

    def check_urls(self, urls: list[str]) -> None:
        """Every URL must answer 200 with the right type; raw.githubusercontent can lag.

        raw.githubusercontent.com serves .mp4 as application/octet-stream, so for
        videos that type is accepted once the first bytes prove it is an MP4.
        """
        for url in urls:
            video = url.endswith(".mp4")
            want = "video/mp4" if video else "image/jpeg"
            for attempt in range(3):
                code, ctype = self.head(url)
                kind = ctype.split(";")[0].strip()
                if code == 200 and kind == want:
                    break
                if code == 200 and video and kind == "application/octet-stream":
                    if self.sniff_mp4(url):
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
        sync = getattr(self.committer, "sync", None)
        if not dry_run and sync is not None:
            sync()
        self.recover(dry_run)

        posts = load_all(self.queue_dir)
        # Account safety (see doxa/pacing.py): pause after a block, gaps, daily cap.
        held = pacing.gate(self.root, [p for _, p in posts], self.now, self.pacing)
        if held:
            for h in held:
                self.log(f"  PACING: {h}")
            if not dry_run:
                self.log("nothing published this run (pacing) — done")
                return 0
            self.log("  (dry run continues so you can preview the request)")
        if post_id:
            chosen = next(((p, post) for p, post in posts if post.id == post_id), None)
            if chosen is None:
                self.log(f"✗ no post with id {post_id}")
                return 1
        else:
            chosen = self.pick(posts)
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

        if post.mode == Mode.reel:
            problems = reel.validate_video(path.parent / reel.VIDEO_NAME)
        else:
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
            self._log_plan(post, urls, blockers, path)
            return 0
        return self._publish(post, path, urls, str(quota))

    def _log_plan(
        self, post: Post, urls: list[str], blockers: list[str], path: Path | None = None
    ) -> None:
        """Log the exact JSON bodies a live run would POST (ids are placeholders)."""
        user = self.client.ig_user_id
        base = f"https://graph.instagram.com/{API_VERSION}/{user}"

        def body(b: dict) -> str:
            return json.dumps(b, ensure_ascii=False)

        if post.mode == Mode.reel:
            self.log(f"  would POST {base}/media  (reel, {post.reel.duration:.1f}s)")
            self.log(f"    {body(Client.reel_body(urls[0], rtl_caption(post.caption)))}")
            self._log_tail(post, base, blockers, "<reel-id>", path)
            return
        for i, url in enumerate(urls, start=1):
            self.log(f"  would POST {base}/media  (child {i}/{len(urls)})")
            self.log(f"    {body(Client.carousel_item_body(url))}")
        children = [f"<child-{i}-id>" for i in range(1, len(urls) + 1)]
        self.log(f"  would POST {base}/media  (carousel)")
        self.log(f"    {body(Client.carousel_body(children, rtl_caption(post.caption)))}")
        self._log_tail(post, base, blockers, "<carousel-id>", path)

    def _log_tail(
        self,
        post: Post,
        base: str,
        blockers: list[str],
        container: str,
        path: Path | None = None,
    ) -> None:
        def body(b: dict) -> str:
            return json.dumps(b, ensure_ascii=False)

        lines = post.caption.rstrip("\n").splitlines()
        self.log(f"  caption: {len(post.caption)} chars, {len(lines)} lines:")
        for line in lines:
            self.log(f"    | {line}")
        self.log(f"  would poll GET /{container}?fields=status_code every {self.poll_s:.0f}s")
        self.log("  would commit status: publishing, then:")
        self.log(f"  would POST {base}/media_publish")
        self.log(f"    {body(Client.publish_body(container))}")
        stories = self.story_urls(post, path) if path is not None else []
        for i, story in enumerate(stories, start=1):
            self.log(f"  then story {i}/{len(stories)}: would POST {base}/media")
            self.log(f"    {body(Client.story_body(story))}")
        if not stories:
            self.log("  then story: none (regular posts are shared by the owner)")
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
            if post.mode == Mode.reel:
                caption = rtl_caption(post.caption)
                parent = self._retry("reel", lambda: c.create_reel_container(urls[0], caption))
                self.log(f"  reel container: {parent}")
                timeout = REEL_PROCESS_TIMEOUT_S
            else:
                children = []
                for i, url in enumerate(urls, start=1):
                    cid = self._retry(f"child {i}", lambda u=url: c.create_carousel_item(u))
                    self.log(f"  child container {i}/{len(urls)}: {cid}")
                    children.append(cid)
                parent = self._retry(
                    "carousel",
                    lambda: c.create_carousel_container(children, rtl_caption(post.caption)),
                )
                self.log(f"  carousel container: {parent}")
                timeout = 300.0
            c.wait_finished(parent, timeout_s=timeout, poll_s=self.poll_s, sleep=self.sleep)
            self.log("  container FINISHED")
        except ActionBlockedError as e:
            return self._blocked(post, path, str(e))
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
        except ActionBlockedError as e:
            # Seen 2026-10-04..07: Instagram answered "restricted" but the post WAS
            # published, so retries made duplicates. Look before deciding.
            live = self._live_on_instagram(post)
            if live is None:
                return self._blocked(post, path, str(e))
            self.log(f"  Instagram said {e}, but the post is live: {live.get('permalink')}")
            self._mark_published(post, path, str(live["id"]), live)
            self.log(f"✓ published {post.id}: {post.permalink}")
            self._story(post, path)
            return 0
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
        self._story(post, path)
        return 0

    def _story(self, post: Post, path: Path) -> None:
        """Share a just-published post as a story: once, best effort.

        A story failure never fails the run or touches the post's status: the
        feed post is already live. The outcome is recorded (story_id or
        story_error) so no later run tries again.
        """
        if post.story_id or post.story_error:
            return
        urls = self.story_urls(post, path)
        if not urls:
            self.log("  story: none (regular posts are shared by the owner)")
            return
        c = self.client
        ids: list[str] = []
        try:
            for i, url in enumerate(urls, start=1):
                timeout = REEL_PROCESS_TIMEOUT_S if url.endswith(".mp4") else 300.0
                self.check_urls([url])
                container = self._retry("story", lambda u=url: c.create_story_container(u))
                self.log(f"  story {i}/{len(urls)} container: {container}")
                c.wait_finished(container, timeout_s=timeout, poll_s=self.poll_s, sleep=self.sleep)
                ids.append(c.publish(container))
                self.log(f"✓ story {i}/{len(urls)} published: {ids[-1]}")
            message = f"publish: {post.id} story"
        except InstagramError as e:
            post.story_error = f"after {len(ids)}/{len(urls)} stories: {e}"[:300]
            self.log(f"  story failed (feed post is fine): {post.story_error}")
            message = f"publish: {post.id} story failed"
        # Comma-separated when a teaser series published several stories.
        post.story_id = ",".join(ids) or None
        self._save(post, path, message)

    def _live_on_instagram(self, post: Post) -> dict | None:
        """The media this run just created for ``post``, if Instagram has it.

        Matches the caption among the newest posts, and only media created in
        the last 15 minutes, so an older copy of the same caption never counts.
        """
        want = normalize_caption(post.caption)
        since = self.now - dt.timedelta(minutes=15)
        for attempt in range(3):
            self.sleep(10 * (attempt + 1))
            try:
                recent = self.client.recent_media()
            except InstagramError as e:
                self.log(f"  could not list recent media: {e}")
                continue
            for m in recent:
                stamp = pacing.parse_meta_time(m.get("timestamp") or "")
                if normalize_caption(m.get("caption") or "") == want and stamp and stamp >= since:
                    return m
        return None

    def _blocked(self, post: Post, path: Path, error: str) -> int:
        """Instagram restricted the account: keep the post for later, pause everything."""
        until = self.now + dt.timedelta(hours=self.pacing.block_pause_hours)
        pause = pacing.write_pause(self.root, until, "Instagram restricted activity")
        self.committer.commit([pause], f"publish: pause until {until:%Y-%m-%d %H:%M}")
        self.log(f"✗ Instagram block, publisher paused until {until:%Y-%m-%d %H:%M}")
        return self._fail(post, path, error, False, retryable=True)

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
