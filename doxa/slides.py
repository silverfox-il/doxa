"""Checks for finished slide JPEGs (``queue/<id>/slides/1.jpg..N.jpg``).

Used for ``mode: prebuilt`` posts and after every render. Kept free of
Playwright so ``doxa validate`` runs anywhere.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .queue import MAX_SLIDES, MIN_SLIDES, slide_files

__all__ = ["slide_files", "validate_slides"]

SLIDE_W = 1080
SLIDE_H = 1350
# Instagram rejects images above 8 MB (Meta docs, POST /<IG_ID>/media).
MAX_BYTES = 8 * 1024 * 1024


def validate_slides(slides_dir: Path) -> list[str]:
    """Return human-readable problems with a slides directory (empty = ok).

    Checks: 2-10 files named ``1.jpg..N.jpg`` (contiguous, nothing else ending
    in .jpg), each a real baseline JPEG, exactly 1080x1350, at most 8 MB.
    """
    if not slides_dir.is_dir():
        return [f"slides directory missing: {slides_dir}"]

    problems: list[str] = []
    all_jpgs = sorted(f.name for f in slides_dir.glob("*.jpg"))
    files = slide_files(slides_dir)
    n = len(files)

    stray = sorted(set(all_jpgs) - {f.name for f in files})
    if stray:
        problems.append(f"unexpected files (name slides 1.jpg..N.jpg): {stray}")
    if not (MIN_SLIDES <= n <= MAX_SLIDES):
        problems.append(f"{n} slides, need {MIN_SLIDES}-{MAX_SLIDES}")
    expected = [f"{i}.jpg" for i in range(1, n + 1)]
    if n and [f.name for f in files] != expected:
        problems.append(f"slide filenames not contiguous 1..{n}: {[f.name for f in files]}")

    for f in files:
        size = f.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{f.name}: {size} bytes, max {MAX_BYTES}")
        try:
            with Image.open(f) as im:
                # Pillow reports extended JPEGs (MPO) as their own format, which
                # Instagram also rejects, so an exact "JPEG" match covers both.
                if im.format != "JPEG":
                    problems.append(f"{f.name}: format {im.format}, need JPEG")
                if im.size != (SLIDE_W, SLIDE_H):
                    problems.append(
                        f"{f.name}: {im.size[0]}x{im.size[1]}, need {SLIDE_W}x{SLIDE_H}"
                    )
                if im.mode not in ("RGB", "L"):
                    problems.append(f"{f.name}: color mode {im.mode}, need RGB")
        except Exception as e:  # noqa: BLE001 — surface any decode error as a problem
            problems.append(f"{f.name}: cannot open as image: {e}")

    return problems
