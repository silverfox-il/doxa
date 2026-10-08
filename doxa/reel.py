"""Text reels (owner-approved prototype style): dark background, white Hebrew
lines that appear one after another, a music bed, 1080x1920, 10-15 s.

Frames come from Chromium (same Heebo font as the carousels, RTL), the video
from ffmpeg (H.264 + AAC, ``+faststart`` so Instagram can stream it). Music is
licensed for use inside videos but not for redistribution as audio files, so
tracks live in the private repo (``private/music``), never in this public one.
"""

from __future__ import annotations

import base64
import html
import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from . import IG_HANDLE
from .queue import REEL_MAX_SECONDS, REEL_MIN_SECONDS, Post, Reel

REEL_W = 1080
REEL_H = 1920
FPS = 30
VIDEO_NAME = "reel.mp4"
# Instagram's limit is far higher; a 15 s text reel is well under 5 MB.
MAX_BYTES = 100 * 1024 * 1024
DURATION_SLACK = 0.3

REPO_ROOT = Path(__file__).resolve().parent.parent
FONT = REPO_ROOT / "assets" / "fonts" / "Heebo[wght].ttf"


class ReelError(Exception):
    pass


def find_music_dir(root: Path) -> Path | None:
    env = os.environ.get("DOXA_MUSIC_DIR")
    candidates = [Path(env)] if env else []
    candidates += [root / "private" / "music", root / "assets" / "music"]
    for c in candidates:
        if c.is_dir() and any(c.glob("*.mp3")):
            return c
    return None


@lru_cache(maxsize=1)
def _css() -> str:
    font = "data:font/ttf;base64," + base64.b64encode(FONT.read_bytes()).decode("ascii")
    return (
        f"@font-face{{font-family:H;src:url('{font}');font-weight:100 900}}"
        "*{margin:0;padding:0;box-sizing:border-box}"
        f"html,body{{width:{REEL_W}px;height:{REEL_H}px;background:#141414}}"
        "body{font-family:H;direction:rtl;color:#fff;display:flex;align-items:center;"
        "justify-content:center;padding:220px 200px 420px 110px}"
        ".w{width:100%;text-align:center}"
        "p{font-size:74px;font-weight:500;line-height:1.28;margin:0 0 74px;white-space:pre-line}"
        ".h{opacity:0}"
        ".tag{position:absolute;bottom:430px;left:110px;right:200px;text-align:center;"
        "font-size:34px;color:#8a8a8a;direction:ltr}"
        # Teaser series (owner's example): black, right aligned, more and smaller
        # lines, like a cynical narrator's notes.
        "body.tease{background:#000;padding:220px 200px 420px 90px}"
        ".tease .w{text-align:right}"
        ".tease p{font-size:58px;font-weight:500;line-height:1.3;margin:0 0 46px}"
        # Boxes (owner's example): text in black rounded boxes on a dark red gradient.
        "body.boxes{background:linear-gradient(180deg,#3a0808 0%,#1c0404 55%,#0d0202 100%);"
        "padding:220px 200px 420px 80px}"
        ".boxes .w{display:flex;flex-direction:column;align-items:center;gap:48px}"
        ".boxes p{background:#000;border-radius:40px;padding:26px 46px;margin:0;"
        "font-size:62px;font-weight:500;line-height:1.28;max-width:940px}"
        ".boxes .tag{color:#c9a3a3}"
        # Over a background video: transparent page, text with a soft shadow.
        "html.video,html.video body{background:transparent}"
        ".video p{text-shadow:0 2px 18px rgba(0,0,0,.85),0 0 4px rgba(0,0,0,.9)}"
        ".video .tag{color:#e6e6e6;text-shadow:0 1px 8px rgba(0,0,0,.9)}"
    )


def frame_html(
    lines: list[str], shown: int, tease: bool = False, look: str = "", video: bool = False
) -> str:
    """Frame with the first ``shown`` lines visible. Hidden lines keep their space,
    so text never jumps as new lines appear."""
    ps = "".join(
        f"<p class='{'' if i < shown else 'h'}'>{html.escape(t)}</p>" for i, t in enumerate(lines)
    )
    return (
        f"<!DOCTYPE html><html dir='rtl' lang='he' class='{'video' if video else ''}'>"
        "<head><meta charset='utf-8'>"
        f"<style>{_css()}</style></head><body class='{look or ('tease' if tease else '')}'>"
        f"<div class='w'>{ps}</div>"
        f"<div class='tag'>{html.escape(IG_HANDLE)}</div></body></html>"
    )


# Instagram draws its own UI over a reel: the header at the top, the like /
# comment / share column on the right, the caption and audio at the bottom. Text
# stays inside the safe area (padding above), and this shrinks every line together
# until the whole block (hidden lines keep their space) fits between y=220 and the
# handle tag.
REEL_FIT_JS = """
() => {
  const H = window.innerHeight, TOP = 220, BOTTOM = H - 480;
  const box = document.querySelector('.w');
  const ps = [...document.querySelectorAll('.w p')];
  const base = ps.map(p => parseFloat(getComputedStyle(p).fontSize));
  const fits = () => {
    const r = box.getBoundingClientRect();
    return r.top >= TOP && r.bottom <= BOTTOM;
  };
  let scale = 1;
  while (!fits() && scale > 0.45) {
    scale -= 0.04;
    ps.forEach((p, i) => { p.style.fontSize = (base[i] * scale) + 'px'; });
  }
  return scale;
}
"""


def render_frames(reel: Reel, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        try:
            page = browser.new_page(viewport={"width": REEL_W, "height": REEL_H})
            for k in range(1, len(reel.lines) + 1):
                doc = frame_html(
                    reel.lines,
                    k,
                    tease=bool(reel.stories),
                    look=reel.style or "",
                    video=bool(reel.video),
                )
                page.set_content(doc, wait_until="load")
                page.evaluate("document.fonts.ready")
                page.evaluate(REEL_FIT_JS)
                out = out_dir / f"{k}.png"
                page.screenshot(path=str(out), type="png", omit_background=bool(reel.video))
                paths.append(out)
        finally:
            browser.close()
    return paths


def find_video_dir(root: Path) -> Path | None:
    """Folder with licensed background clips (private repo, like the music)."""
    env = os.environ.get("DOXA_VIDEO_DIR")
    candidates = [Path(env)] if env else []
    candidates += [root / "private" / "video", root / "assets" / "video"]
    if os.environ.get("DOXA_MUSIC_DIR"):
        candidates.append(Path(os.environ["DOXA_MUSIC_DIR"]).parent / "video")
    for c in candidates:
        if c.is_dir() and any(c.glob("*.mp4")):
            return c
    return None


# How much to darken the clip so white text stays readable (0 = none, 1 = black).
VIDEO_SHADE = 0.5


def ffmpeg_cmd(
    frames: list[Path],
    reel: Reel,
    music: Path,
    out: Path,
    concat: Path,
    video: Path | None = None,
) -> list[str]:
    durations = [reel.per_line] * (len(frames) - 1) + [reel.hold]
    body = "".join(
        f"file '{f.resolve().as_posix()}'\nduration {d}\n"
        for f, d in zip(frames, durations, strict=True)
    )
    # The concat demuxer needs the last frame listed twice to honour its duration.
    concat.write_text(body + f"file '{frames[-1].resolve().as_posix()}'\n", encoding="utf-8")
    total = reel.duration
    if video is not None:
        # Text frames (with alpha) over the looped clip, cropped to 9:16 and shaded.
        graph = (
            f"[1:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
            f"crop={REEL_W}:{REEL_H},fps={FPS},setsar=1,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{VIDEO_SHADE}:t=fill[bg];"
            f"[0:v]fps={FPS},format=rgba[txt];"
            "[bg][txt]overlay=0:0:shortest=0,format=yuv420p[v]"
        )
        return [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-stream_loop", "-1", "-i", str(video),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", graph, "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-profile:v", "high", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-af", f"afade=t=in:d=0.8,afade=t=out:st={total - 1.2:.2f}:d=1.2",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(out),
        ]  # fmt: skip
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-stream_loop", "-1", "-i", str(music),
        "-vf", f"fps={FPS},format=yuv420p",
        "-c:v", "libx264", "-profile:v", "high", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-af", f"afade=t=in:d=0.8,afade=t=out:st={total - 1.2:.2f}:d=1.2",
        "-t", f"{total:.2f}", "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def render_reel(post: Post, post_dir: Path, *, root: Path = REPO_ROOT) -> Path:
    """Render ``reel.mp4`` for a ``mode: reel`` post."""
    if post.reel is None:
        raise ReelError(f"{post.id} has no reel: block")
    if shutil.which("ffmpeg") is None:
        raise ReelError("ffmpeg not found on PATH")
    music_dir = find_music_dir(root)
    if music_dir is None:
        raise ReelError("no music folder (private/music or DOXA_MUSIC_DIR)")
    music = music_dir / post.reel.music
    if not music.is_file():
        raise ReelError(f"music track not found: {post.reel.music}")
    clip = None
    if post.reel.video:
        video_dir = find_video_dir(root)
        if video_dir is None or not (video_dir / post.reel.video).is_file():
            raise ReelError(f"background video not found: {post.reel.video}")
        clip = video_dir / post.reel.video
    out = post_dir / VIDEO_NAME
    with tempfile.TemporaryDirectory() as tmp:
        frames = render_frames(post.reel, Path(tmp))
        cmd = ffmpeg_cmd(frames, post.reel, music, out, Path(tmp) / "list.txt", clip)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ReelError(f"ffmpeg failed: {proc.stderr.strip()[-500:]}")
    return out


def probe(video: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ReelError(f"ffprobe failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def validate_video(video: Path) -> list[str]:
    """Problems with a rendered reel (empty = ok)."""
    if not video.is_file():
        return [f"{video.name} missing"]
    problems = []
    if video.stat().st_size > MAX_BYTES:
        problems.append(f"{video.name}: {video.stat().st_size} bytes, max {MAX_BYTES}")
    if shutil.which("ffprobe") is None:
        return problems + ["ffprobe not found on PATH, cannot inspect the video"]
    try:
        info = probe(video)
    except ReelError as e:
        return problems + [str(e)]
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        problems.append("no video stream")
    else:
        if v.get("codec_name") != "h264":
            problems.append(f"video codec {v.get('codec_name')}, need h264")
        if (v.get("width"), v.get("height")) != (REEL_W, REEL_H):
            problems.append(f"{v.get('width')}x{v.get('height')}, need {REEL_W}x{REEL_H}")
        if v.get("pix_fmt") != "yuv420p":
            problems.append(f"pixel format {v.get('pix_fmt')}, need yuv420p")
    if a is None:
        problems.append("no audio stream")
    elif a.get("codec_name") != "aac":
        problems.append(f"audio codec {a.get('codec_name')}, need aac")
    duration = float(info.get("format", {}).get("duration", 0))
    if not (REEL_MIN_SECONDS - DURATION_SLACK <= duration <= REEL_MAX_SECONDS + DURATION_SLACK):
        problems.append(
            f"duration {duration:.1f}s, need {REEL_MIN_SECONDS:.0f}-{REEL_MAX_SECONDS:.0f}s"
        )
    return problems
