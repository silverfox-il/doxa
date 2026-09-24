"""``doxa`` command-line interface.

* ``doxa validate``        — validate every post.yaml (and any committed slide JPEGs).
* ``doxa render [ID...]``   — render render-mode posts; validate prebuilt ones.
* ``doxa changed BASE HEAD`` — print post ids touched between two commits.
* ``doxa status``          — regenerate STATUS.md.
* ``doxa open-issues ID...`` — open/refresh the approval issue for rendered posts.
* ``doxa approve-sync``    — copy the issue's ``approved`` label into post.yaml.
* ``doxa publish``         — milestone 4; registered as a stub that refuses to run.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import click

from . import slides, status
from .queue import (
    POST_ID_RE,
    RENDERABLE_STATUSES,
    TZ,
    Mode,
    Post,
    QueueError,
    Status,
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
        # Prebuilt posts must always ship JPEGs; rendered posts must have kept them.
        if post.mode == Mode.prebuilt or post.status != Status.queued:
            errors.extend(f"{rel}: {p}" for p in slides.validate_slides(path.parent / "slides"))
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
    """Render POST_IDS (default: every queued/rendered post) to slides/*.jpg.

    Prebuilt posts are only validated. Posts already publishing, published or
    failed are never touched, so a re-render can never make them publishable.
    """
    from . import render

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
        problems = slides.validate_slides(post_dir / "slides")
        if problems:
            _fail([f"{post.id}: {p}" for p in problems])
        if post.status != Status.rendered:
            post.status = Status.rendered
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


@main.command("open-issues")
@click.argument("post_ids", nargs=-1)
@click.option("--sha", envvar="DOXA_SHA", required=True, help="Commit SHA to pin raw URLs to.")
@click.pass_context
def open_issues(ctx: click.Context, post_ids: tuple[str, ...], sha: str) -> None:
    """Open or refresh the `Approve: <id>` issue for rendered POST_IDS."""
    from . import approval, github

    slug = github.repo_slug()
    approval.ensure_approved_label()
    for path, post in _select(ctx.obj["root"], post_ids):
        if post.status != Status.rendered:
            click.echo(f"- {post.id}: status {post.status.value}, no approval issue")
            continue
        n = len(slides.slide_files(path.parent / "slides"))
        number, created = approval.upsert_approval_issue(post, slug, sha, n)
        click.echo(f"✓ {post.id}: {'opened' if created else 'updated'} issue #{number}")


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


@main.command()
def publish() -> None:
    """(milestone 4) Publish one due, approved post. Not implemented yet."""
    click.echo("publish is implemented in milestone 4", err=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
