"""Golden fixtures for the renderer's visual regression test.

The fixtures cover the bidi cases the spec calls out ("בגיל 50." and "25:"),
every layout, and the last-slide handle. The background is a synthetic
gradient so nothing here depends on a licensed photo.

Goldens are the Linux/Chromium output from CI. To accept an intentional visual
change, commit an empty ``tests/golden/REGENERATE`` file: the ``goldens``
workflow re-renders on ubuntu, commits the PNGs and deletes the marker.
Locally, ``python -m tests.golden.gen`` writes the same PNGs for inspection;
don't commit goldens made on another OS.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from doxa import render
from doxa.queue import Layout, Slide
from doxa.slides import SLIDE_H, SLIDE_W

HERE = Path(__file__).resolve().parent
# Fixture slides resolve "assets/..." against this directory, like the repo root.
ROOT = HERE / "root"
BG = "assets/backgrounds/gradient.jpg"
# Marker file: when committed, the goldens workflow re-renders and removes it.
REGENERATE = HERE / "REGENERATE"

FIXTURES: list[tuple[str, Slide]] = [
    (
        "bidi_number_period",
        Slide(
            background=BG,
            kicker="פוסט ראשון",
            title="בגיל 50.\nאתה לא גמור",
            accent="אתה בשיא",
            body="רק שכחו להגיד לך",
            layout=Layout.bottom,
        ),
    ),
    (
        "bidi_colon_list",
        Slide(
            background=BG,
            kicker="שלושה דברים",
            title="25: הכללים",
            layout=Layout.list,
            items=["גוף: 3 אימונים בשבוע.", "ביטחון", "דייטינג שעובד היום"],
        ),
    ),
    (
        "top_last_handle",
        Slide(
            background=BG,
            title="25:",
            accent="שנים של ניסיון",
            body='תעקוב, ותגיב "בפנים".',
            layout=Layout.top,
        ),
    ),
]

TOTAL = len(FIXTURES)


def make_background(path: Path) -> None:
    """Deterministic vertical slate gradient (JPEG)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (SLIDE_W, SLIDE_H))
    for y in range(SLIDE_H):
        t = y / SLIDE_H
        row = (int(70 - 40 * t), int(78 - 44 * t), int(96 - 54 * t))
        img.paste(row, (0, y, SLIDE_W, y + 1))
    img.save(path, "JPEG", quality=90)


def ensure_background() -> None:
    path = ROOT / BG
    if not path.exists():
        make_background(path)


def fixture_html(index: int) -> str:
    """HTML for fixture ``index`` (1-based)."""
    ensure_background()
    return render.build_html(FIXTURES[index - 1][1], index, TOTAL, root=ROOT)


def golden_path(name: str) -> Path:
    return HERE / f"{name}.png"


def render_fixture(renderer: render.Renderer, name: str) -> Image.Image:
    index = [n for n, _ in FIXTURES].index(name) + 1
    png = renderer.screenshot(fixture_html(index), fmt="png")
    return Image.open(io.BytesIO(png)).convert("RGB")


def main() -> None:
    with render.Renderer() as r:
        images = {name: render_fixture(r, name) for name, _ in FIXTURES}
    for name, img in images.items():
        img.save(golden_path(name), "PNG", optimize=True)
        print(f"wrote {golden_path(name).relative_to(HERE.parent.parent).as_posix()}")


if __name__ == "__main__":
    main()
