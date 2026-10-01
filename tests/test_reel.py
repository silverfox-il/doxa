"""Text reels: schema, rendering (Playwright + ffmpeg) and video validation."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from doxa import reel
from doxa.cli import main
from doxa.queue import Post, Reel, Status, load_post

from .conftest import render_post_data, write_post

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

LINES = ["תזכור:", "אתה לא מתחרה עם השכן מהקומה השנייה,", "כל ערב לפני שהיא נרדמת."]


def reel_data(post_id="2026-10-03-reel", **reel_kw) -> dict:
    spec = {"lines": LINES, "music": "track.mp3", "per_line": 3.0, "hold": 5.0, **reel_kw}
    return render_post_data(post_id, mode="reel", slides=[], caption="תזכור:", reel=spec)


# --- schema ---------------------------------------------------------------------


def test_reel_duration_is_computed_and_bounded():
    assert Reel(lines=LINES, music="t.mp3", per_line=3.0, hold=5.0).duration == 11.0
    with pytest.raises(ValidationError, match="need 10-15s"):
        Reel(lines=LINES, music="t.mp3", per_line=1.0, hold=2.0)
    with pytest.raises(ValidationError, match="need 10-15s"):
        Reel(lines=LINES, music="t.mp3", per_line=6.0, hold=6.0)


@pytest.mark.parametrize(
    "kw,msg",
    [
        ({"lines": ["רק שורה אחת"]}, "2-6 lines"),
        ({"lines": ["א", " "]}, "must not be empty"),
        ({"music": "../secret.mp3"}, "bare .mp3"),
        ({"music": "song.wav"}, "bare .mp3"),
    ],
)
def test_reel_shape_rules(kw, msg):
    with pytest.raises(ValidationError, match=msg):
        Post.model_validate(reel_data(**kw))


def test_mode_and_block_must_match():
    with pytest.raises(ValidationError, match="needs a reel: block"):
        Post.model_validate(render_post_data(mode="reel", slides=[]))
    data = render_post_data()
    data["reel"] = {"lines": LINES, "music": "t.mp3", "per_line": 3, "hold": 5}
    with pytest.raises(ValidationError, match="only for mode: reel"):
        Post.model_validate(data)


def test_frame_html_keeps_hidden_lines_in_layout_and_escapes():
    doc = reel.frame_html(["<b>א</b>", "ב", "ג"], 1)
    assert doc.count("class='h'") == 2  # not yet shown, but still taking space
    assert "&lt;b&gt;א&lt;/b&gt;" in doc
    assert "@the_silver_fox_men" in doc and "dir='rtl'" in doc


def test_ffmpeg_command_shape(tmp_path):
    frames = [tmp_path / f"{i}.png" for i in (1, 2, 3)]
    r = Reel(lines=LINES, music="t.mp3", per_line=3.0, hold=5.0)
    cmd = reel.ffmpeg_cmd(frames, r, tmp_path / "t.mp3", tmp_path / "o.mp4", tmp_path / "l.txt")
    listing = (tmp_path / "l.txt").read_text(encoding="utf-8")
    assert listing.count("duration 3.0") == 2 and "duration 5.0" in listing
    assert listing.strip().endswith("3.png'")  # last frame repeated for the demuxer
    assert cmd[cmd.index("-t") + 1] == "11.00"
    assert "+faststart" in cmd and "libx264" in cmd and "aac" in cmd


# --- render + validate (needs ffmpeg and Chromium) --------------------------------


@pytest.fixture
def music_dir(tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    d = tmp_path / "music"
    d.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
         str(d / "track.mp3")],
        check=True,
    )  # fmt: skip
    monkeypatch.setenv("DOXA_MUSIC_DIR", str(d))
    return d


@needs_ffmpeg
def test_render_reel_end_to_end_via_cli(repo, music_dir):
    pytest.importorskip("playwright.sync_api")
    path = write_post(repo, reel_data())
    result = CliRunner().invoke(main, ["--root", str(repo), "render", "2026-10-03-reel"])
    assert result.exit_code == 0, result.output
    video = path.parent / reel.VIDEO_NAME
    assert reel.validate_video(video) == []
    info = reel.probe(video)
    assert abs(float(info["format"]["duration"]) - 11.0) < 0.2  # music looped to fill
    assert load_post(path).status == Status.rendered
    assert CliRunner().invoke(main, ["--root", str(repo), "validate"]).exit_code == 0


@needs_ffmpeg
def test_validate_video_rejects_wrong_format(tmp_path):
    bad = tmp_path / "bad.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x480:d=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(bad)],
        check=True,
    )  # fmt: skip
    problems = reel.validate_video(bad)
    assert "640x480, need 1080x1920" in problems
    assert "no audio stream" in problems
    assert any(p.startswith("duration 3.0s") for p in problems)
    assert reel.validate_video(tmp_path / "missing.mp4") == ["missing.mp4 missing"]


def test_missing_track_is_a_clear_error(repo, music_dir):
    path = write_post(repo, reel_data(music="nope.mp3"))
    with pytest.raises(reel.ReelError, match="music track not found: nope.mp3"):
        reel.render_reel(load_post(path), path.parent, root=repo)


def test_rendered_reel_without_video_fails_validate(repo):
    write_post(repo, {**reel_data(), "status": "rendered"})
    result = CliRunner().invoke(main, ["--root", str(repo), "validate"])
    assert result.exit_code == 1 and "reel.mp4 missing" in result.output
