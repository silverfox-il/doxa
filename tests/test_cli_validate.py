"""`doxa validate` against a temporary queue."""

from __future__ import annotations

from click.testing import CliRunner

from doxa.cli import main

from .conftest import make_jpeg, render_post_data, write_post


def run(root, *args):
    return CliRunner().invoke(main, ["--root", str(root), *args])


def test_empty_queue_is_ok(repo):
    result = run(repo, "validate")
    assert result.exit_code == 0
    assert "no posts" in result.output


def test_valid_render_post(repo):
    write_post(repo, render_post_data())
    result = run(repo, "validate")
    assert result.exit_code == 0, result.output
    assert "1 post(s) valid" in result.output


def test_reports_every_problem_with_repo_relative_paths(repo):
    write_post(repo, render_post_data("2026-09-25-a", publish_at="tomorrow"))
    data = render_post_data("2026-09-26-b")
    data["slides"][0]["background"] = "assets/backgrounds/missing.jpg"
    write_post(repo, data)
    write_post(repo, render_post_data("2026-09-27-c"), dirname="2026-09-27-other")

    result = run(repo, "validate")
    assert result.exit_code == 1
    assert "queue/2026-09-25-a/post.yaml" in result.output
    assert "publish_at" in result.output
    assert "background not found: assets/backgrounds/missing.jpg" in result.output
    assert "id '2026-09-27-c' != directory '2026-09-27-other'" in result.output
    assert "3 problem(s) in 3 post(s)" in result.output


def test_prebuilt_post_checks_jpegs(repo):
    data = render_post_data("2026-09-25-pre", mode="prebuilt", slides=[])
    path = write_post(repo, data)
    slides = path.parent / "slides"
    make_jpeg(slides / "1.jpg")
    make_jpeg(slides / "2.jpg", size=(1080, 1080))
    make_jpeg(slides / "4.jpg")

    result = run(repo, "validate")
    assert result.exit_code == 1
    assert "2.jpg: 1080x1080, need 1080x1350" in result.output
    assert "not contiguous" in result.output

    (slides / "4.jpg").rename(slides / "3.jpg")
    make_jpeg(slides / "2.jpg")
    assert run(repo, "validate").exit_code == 0


def test_prebuilt_rejects_png_named_jpg_and_too_few(repo):
    path = write_post(repo, render_post_data("2026-09-25-pre", mode="prebuilt", slides=[]))
    fake = path.parent / "slides" / "1.jpg"
    fake.parent.mkdir()
    from PIL import Image

    Image.new("RGB", (1080, 1350)).save(fake, "PNG")
    result = run(repo, "validate")
    assert "format PNG, need JPEG" in result.output
    assert "1 slides, need 2-10" in result.output


def test_publish_without_secrets_refuses(repo, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("IG_USER_ID", raising=False)
    result = run(repo, "publish")
    assert result.exit_code == 1
    assert "IG_ACCESS_TOKEN, IG_USER_ID not set" in result.output
