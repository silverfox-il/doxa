"""``doxa`` command-line interface.

* ``doxa validate``        — validate every post.yaml (and any committed slide JPEGs).
* ``doxa render [ID...]``   — render render-mode posts; validate prebuilt ones.
* ``doxa changed BASE HEAD`` — print post ids touched between two commits.
* ``doxa status``          — regenerate STATUS.md.
* ``doxa open-issues ID...`` — open/refresh the approval issue for rendered posts.
* ``doxa approve-sync``    — copy the issue's ``approved`` label into post.yaml.
* ``doxa publish``         — publish one approved, due post (dry run unless ``--live``).
* ``doxa check``           — verify the Instagram token: prints username, user_id, quota.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import click

from . import reel, rules, slides, status
from .queue import (
    POST_ID_RE,
    RENDERABLE_STATUSES,
    TZ,
    ApprovedBy,
    Mode,
    Post,
    QueueError,
    Status,
    approval_is_current,
    dump_post,
    iter_post_files,
    load_post,
    post_ids_from_paths,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _queue_dir(root: Path) -> Path:
    return root / "queue"


def _now() -> dt.datetime:
    return dt.datetime.now(TZ)


def _fail(lines: list[str]) -> NoReturn:
    for line in lines:
        click.echo(f"✗ {line}", err=True)
    sys.exit(1)


def validate_queue(root: Path) -> tuple[int, list[str]]:
    """Validate every post under ``root/queue``. Returns (post count, problems)."""
    files = iter_post_files(_queue_dir(root))
    errors: list[str] = []
    cfg, book = rules.load_context(root)
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            post = load_post(path)
        except QueueError as e:
            errors.append(str(e).replace(str(path), rel, 1))
            continue
        if post.id != path.parent.name:
            errors.append(f"{rel}: id '{post.id}' != directory '{path.parent.name}'")
        if post.mode == Mode.render:
            for i, slide in enumerate(post.slides, start=1):
                if not (root / slide.background).is_file():
                    errors.append(f"{rel}: slide {i} background not found: {slide.background}")
        if post.mode == Mode.reel:
            if post.status != Status.queued:
                video = path.parent / reel.VIDEO_NAME
                errors.extend(f"{rel}: {p}" for p in reel.validate_video(video))
        # Prebuilt posts must always ship JPEGs; rendered posts must have kept them.
        elif post.mode == Mode.prebuilt or post.status != Status.queued:
            errors.extend(f"{rel}: {p}" for p in slides.validate_slides(path.parent / "slides"))
        # Content rules apply to everything that has not gone out yet.
        if post.status not in (Status.published, Status.publishing):
            for f in rules.blocking(rules.check_post(post, cfg, book)):
                errors.append(f"{rel}: {f}")
    loaded = []
    for path in files:
        try:
            loaded.append(load_post(path))
        except QueueError:
            pass  # already reported above
    errors += [f"queue: {f}" for f in rules.repeated_quotes(loaded)]
    return len(files), errors


@click.group()
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=REPO_ROOT,
    help="Repo root (defaults to the doxa checkout).",
)
@click.pass_context
def main(ctx: click.Context, root: Path) -> None:
    """DOXA — Instagram carousel publisher for @the_silver_fox_men."""
    # Hebrew and check marks must print on any console (Windows cp1252, CI pipes).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ctx.ensure_object(dict)
    ctx.obj["root"] = root.resolve()


@main.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate every post.yaml against the schema; check slide JPEGs."""
    count, errors = validate_queue(ctx.obj["root"])
    if errors:
        for e in errors:
            click.echo(f"✗ {e}", err=True)
        click.echo(f"\n{len(errors)} problem(s) in {count} post(s)", err=True)
        sys.exit(1)
    click.echo(f"✓ {count} post(s) valid" if count else "no posts in queue/")


def _select(root: Path, post_ids: tuple[str, ...]) -> list[tuple[Path, Post]]:
    """Load the named posts (all when empty); unknown ids are reported and skipped."""
    queue_dir = _queue_dir(root)
    if post_ids:
        paths = []
        for pid in post_ids:
            path = queue_dir / pid / "post.yaml"
            if not POST_ID_RE.match(pid):
                _fail([f"not a post id: {pid!r}"])
            if path.is_file():
                paths.append(path)
            else:
                click.echo(f"- {pid}: no post.yaml, skipping")
    else:
        paths = iter_post_files(queue_dir)
    try:
        return [(p, load_post(p)) for p in paths]
    except QueueError as e:
        _fail([str(e)])


@main.command("render")
@click.argument("post_ids", nargs=-1)
@click.pass_context
def render_cmd(ctx: click.Context, post_ids: tuple[str, ...]) -> None:
    """Render POST_IDS (default: every queued/rendered post).

    Carousels become slides/*.jpg, reels become reel.mp4. Prebuilt posts are
    only validated. Posts already publishing, published or
    failed are never touched, so a re-render can never make them publishable.
    """
    from . import approval, render

    root: Path = ctx.obj["root"]
    done: list[str] = []
    for path, post in _select(root, post_ids):
        if post.status not in RENDERABLE_STATUSES:
            click.echo(f"- {post.id}: status {post.status.value}, not re-rendering")
            continue
        post_dir = path.parent
        if post.mode == Mode.render:
            click.echo(f"rendering {post.id} ({len(post.slides)} slides)…")
            try:
                render.render_post(post, post_dir, root=root)
            except render.RenderError as e:
                _fail([f"{post.id}: {e}"])
        if post.mode == Mode.reel:
            click.echo(f"rendering reel {post.id} ({post.reel.duration:.1f}s)…")
            try:
                reel.render_reel(post, post_dir, root=root)
            except reel.ReelError as e:
                _fail([f"{post.id}: {e}"])
            problems = reel.validate_video(post_dir / reel.VIDEO_NAME)
        else:
            problems = slides.validate_slides(post_dir / "slides")
        if problems:
            _fail([f"{post.id}: {p}" for p in problems])
        before = post.model_copy()
        post.status = Status.rendered
        outcome = approval.reconcile(post, post_dir, _now())
        if outcome == "reset":
            click.echo(f"! {post.id}: changed after approval, approval reset")
        elif outcome == "stamped":
            click.echo(f"✓ {post.id}: approved in post.yaml, content hash recorded")
        if post != before:
            dump_post(post, path)
        done.append(post.id)
        click.echo(f"✓ {post.id} ready ({post.mode.value})")

    status.write_status(root, _now())
    click.echo(f"{len(done)} post(s) rendered/validated")


@main.command()
@click.argument("base")
@click.argument("head")
@click.pass_context
def changed(ctx: click.Context, base: str, head: str) -> None:
    """Print ids of posts touched between commits BASE and HEAD, one per line.

    An all-zero or unknown BASE (first push, force push) means "every post".
    """
    root: Path = ctx.obj["root"]
    all_ids = [p.parent.name for p in iter_post_files(_queue_dir(root))]
    if set(base) == {"0"}:
        ids = all_ids
    else:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base, head, "--", "queue/"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            click.echo(f"git diff failed ({proc.stderr.strip()}); using every post", err=True)
            ids = all_ids
        else:
            ids = post_ids_from_paths(proc.stdout.splitlines())
    for pid in ids:
        click.echo(pid)


@main.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Regenerate STATUS.md."""
    out = status.write_status(ctx.obj["root"], _now())
    click.echo(f"✓ wrote {out.name}")


@main.command("rules")
@click.argument("post_ids", nargs=-1)
@click.option("--strict", is_flag=True, help="Fail on review findings too, not only blocks.")
@click.pass_context
def rules_cmd(ctx: click.Context, post_ids: tuple[str, ...], strict: bool) -> None:
    """Check content rules (verbatim, banned words, dashes, ages, identity...)."""
    root: Path = ctx.obj["root"]
    cfg, book = rules.load_context(root)
    if book is None:
        click.echo("! book not found: verbatim check cannot run", err=True)
    failed = 0
    for _, post in _select(root, post_ids):
        if post.status in (Status.published, Status.publishing):
            continue
        findings = rules.check_post(post, cfg, book)
        bad = findings if strict else rules.blocking(findings)
        mark = "✗" if bad else ("!" if findings else "✓")
        click.echo(f"{mark} {post.id}")
        for f in findings:
            click.echo(f"    {f}")
        failed += bool(bad)
    if failed:
        _fail([f"{failed} post(s) break the content rules"])


@main.command()
@click.pass_context
def used(ctx: click.Context) -> None:
    """Write content/used.yaml: every book passage the queue has used, by post."""
    import yaml

    root: Path = ctx.obj["root"]
    entries = []
    for _, post in sorted(_select(root, ()), key=lambda pp: pp[1].publish_at):
        entries.append(
            {
                "id": post.id,
                "publish_at": post.publish_at,
                "status": post.status.value,
                "source": post.source.key if post.source else None,
                "quotes": rules.quotes(post),
            }
        )
    out = root / "content" / "used.yaml"
    out.parent.mkdir(exist_ok=True)
    header = "# Generated by `doxa used`. Book passages in the queue; never reuse them.\n"
    out.write_text(
        header + yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    click.echo(f"✓ {len(entries)} post(s) -> {out.relative_to(root).as_posix()}")


@main.command("open-issues")
@click.argument("post_ids", nargs=-1)
@click.option("--sha", envvar="DOXA_SHA", required=True, help="Commit SHA to pin raw URLs to.")
@click.pass_context
def open_issues(ctx: click.Context, post_ids: tuple[str, ...], sha: str) -> None:
    """Open or refresh the `Approve: <id>` issue for rendered POST_IDS."""
    from . import approval, github

    slug = github.repo_slug()
    approval.ensure_labels()
    for path, post in _select(ctx.obj["root"], post_ids):
        if post.status != Status.rendered:
            click.echo(f"- {post.id}: status {post.status.value}, no approval issue")
            continue
        n = len(slides.slide_files(path.parent / "slides"))
        number, created = approval.upsert_approval_issue(post, path.parent, slug, sha, n)
        click.echo(f"✓ {post.id}: {'opened' if created else 'updated'} issue #{number}")
        if post.approved_by == ApprovedBy.auto and approval_is_current(post, path.parent):
            github.add_label(number, approval.AUTO_LABEL)


@main.command("auto-approve")
@click.argument("post_ids", nargs=-1)
@click.pass_context
def auto_approve(ctx: click.Context, post_ids: tuple[str, ...]) -> None:
    """Approve rendered POST_IDS that pass every automatic check.

    A post qualifies only if its media is valid, the book is available and
    every content rule passes with no finding at all (block or review). The
    owner keeps a veto: auto-approved posts wait 24 hours and never publish
    while the issue has the `hold` label. Run only when DOXA_AUTO_APPROVE=true.
    """
    from . import approval

    root: Path = ctx.obj["root"]
    cfg, book = rules.load_context(root)
    if book is None:
        _fail(["book not found: auto-approve needs it to verify verbatim quotes"])
    approved = 0
    for path, post in _select(root, post_ids):
        if post.status != Status.rendered or approval_is_current(post, path.parent):
            continue
        if post.mode == Mode.reel:
            problems = reel.validate_video(path.parent / reel.VIDEO_NAME)
        else:
            problems = slides.validate_slides(path.parent / "slides")
        problems += [str(f) for f in rules.check_post(post, cfg, book)]
        if problems:
            click.echo(f"- {post.id}: needs the owner")
            for p in problems:
                click.echo(f"    {p}")
            continue
        approval.stamp(post, path.parent, ApprovedBy.auto, _now())
        dump_post(post, path)
        approved += 1
        click.echo(f"✓ {post.id}: auto-approved")
    click.echo(f"{approved} post(s) auto-approved")


@main.command("approve-sync")
@click.argument("post_ids", nargs=-1)
@click.option(
    "--from-issue-title",
    "issue_title",
    default=None,
    help="Take the post id from an approval issue title (as sent by approve.yml).",
)
@click.pass_context
def approve_sync(ctx: click.Context, post_ids: tuple[str, ...], issue_title: str | None) -> None:
    """Write `approved: true` for posts whose approval issue has the `approved` label."""
    from . import approval

    if issue_title is not None:
        pid = approval.post_id_from_title(issue_title)
        if pid is None:
            _fail([f"not an approval issue title: {issue_title!r}"])
        post_ids = (*post_ids, pid)
    changed_ids = []
    for path, post in _select(ctx.obj["root"], post_ids):
        if approval.sync_label_to_yaml(post.id, path):
            changed_ids.append(post.id)
            click.echo(f"✓ {post.id}: approved via label")
    click.echo(f"{len(changed_ids)} post(s) updated")


def _client():
    """Instagram client from IG_ACCESS_TOKEN / IG_USER_ID. Never echoes either value."""
    import os

    from .instagram import Client

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("IG_USER_ID", "").strip()
    missing = [n for n, v in (("IG_ACCESS_TOKEN", token), ("IG_USER_ID", user_id)) if not v]
    if missing:
        _fail([f"{', '.join(missing)} not set (repo secrets in Actions, env vars locally)"])
    return Client(access_token=token, ig_user_id=user_id)


def _head_sha(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


@main.command()
@click.option(
    "--dry-run/--live",
    default=True,
    help="Dry run (default) makes no POST to Meta and commits nothing. --live publishes.",
)
@click.option("--post-id", default=None, help="Publish this post instead of the oldest due one.")
@click.option("--sha", envvar="DOXA_SHA", default=None, help="Commit to pin image URLs to.")
@click.pass_context
def publish(ctx: click.Context, dry_run: bool, post_id: str | None, sha: str | None) -> None:
    """Publish at most one approved, due post to Instagram."""
    from . import github
    from .publish import GitCommitter, Publisher

    root: Path = ctx.obj["root"]
    if post_id and not POST_ID_RE.match(post_id):
        _fail([f"not a post id: {post_id!r}"])
    publisher = Publisher(
        root=root,
        client=_client(),
        slug=github.repo_slug(),
        sha=sha or _head_sha(root),
        committer=GitCommitter(root),
        log=click.echo,
    )
    sys.exit(publisher.run(dry_run=dry_run, post_id=post_id))


@main.command()
@click.option("--expect-username", default=None, help="Fail unless the token belongs to this.")
def check(expect_username: str | None) -> None:
    """Check the Instagram token: print ONLY username, user_id and quota."""
    from .instagram import InstagramError

    client = _client()
    try:
        me = client.me()
        quota = client.publishing_quota()
    except InstagramError as e:
        _fail([str(e)])
    click.echo(f"username: {me['username']}")
    click.echo(f"user_id:  {me['user_id']}")
    click.echo(f"quota:    {quota}")
    problems = []
    if me["user_id"] != client.ig_user_id:
        problems.append("IG_USER_ID does not match the account the token belongs to")
    if expect_username and me["username"] != expect_username:
        problems.append(f"expected username {expect_username}")
    if problems:
        _fail(problems)


if __name__ == "__main__":
    main()
