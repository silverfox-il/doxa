"""Renderer tests (spec §3): bidi geometry everywhere, pixel goldens on Linux.

* ``test_bidi_*`` read glyph positions from the live DOM, so they catch a
  punctuation/number flip on any OS without depending on font rasterisation.
* ``test_golden_matches`` compares full renders with committed PNGs made on
  ubuntu CI. Font rasterisation differs across OSes, so it only runs on Linux
  (or with ``DOXA_GOLDEN=1``). On failure the render and a diff image are
  written to ``tests/_out/`` (uploaded as a CI artifact).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageFilter

pytest.importorskip("playwright.sync_api")

from doxa import render  # noqa: E402
from doxa.queue import Mode, Post, Slide  # noqa: E402
from doxa.slides import SLIDE_H, SLIDE_W, validate_slides  # noqa: E402

from .golden import gen  # noqa: E402

OUT = Path(__file__).resolve().parent / "_out"

# Compare at 1/4 size after a light blur: anti-aliasing noise averages out,
# while a glyph that moved (bidi flip) or vanished still leaves a hot spot.
SCALE = 4
PIXEL_THRESHOLD = 24  # max channel difference (0-255) before a pixel is "hot"
MAX_HOT_PIXELS = 12  # hot pixels tolerated per slide

# x-centre of the first occurrence of each char inside `selector`.
_GLYPH_X_JS = """
([selector, chars]) => {
  const el = document.querySelector(selector);
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n);
  const out = {};
  for (const ch of chars) {
    for (const node of nodes) {
      const i = node.data.indexOf(ch);
      if (i < 0) continue;
      const range = document.createRange();
      range.setStart(node, i);
      range.setEnd(node, i + ch.length);
      const r = range.getBoundingClientRect();
      out[ch] = r.left + r.width / 2;
      break;
    }
  }
  return out;
}
"""


@pytest.fixture(scope="module")
def renderer():
    with render.Renderer() as r:
        yield r


def glyph_x(renderer, index: int, selector: str, chars: list[str]) -> dict[str, float]:
    renderer.load(gen.fixture_html(index))
    xs = renderer.page.evaluate(_GLYPH_X_JS, [selector, chars])
    assert set(xs) == set(chars), f"missing glyphs in {selector}: {set(chars) - set(xs)}"
    return xs


def test_bidi_trailing_period_sits_left_of_number(renderer):
    # "בגיל 50." reads right-to-left: Hebrew, then "50", then the period at the
    # far left. The digits keep their LTR order ("5" left of "0").
    x = glyph_x(renderer, 1, ".title", ["ב", "5", "0", "."])
    assert x["."] < x["5"] < x["0"] < x["ב"]


def test_bidi_colon_after_number(renderer):
    # "25: הכללים": number at the right edge, colon to its left, then Hebrew.
    x = glyph_x(renderer, 2, ".title", ["ה", ":", "2", "5"])
    assert x["ה"] < x[":"] < x["2"] < x["5"]
    # Standalone "25:": colon on the left of the number.
    x = glyph_x(renderer, 3, ".title", [":", "2", "5"])
    assert x[":"] < x["2"] < x["5"]


def test_bidi_list_item_number_and_period(renderer):
    # "גוף: 3 אימונים בשבוע." — trailing period at the far left of the line.
    x = glyph_x(renderer, 2, ".items li", ["ג", ":", "3", "."])
    assert x["."] < x["3"] < x[":"] < x["ג"]


def test_frame_brand_right_counter_left_font_loaded(renderer):
    renderer.load(gen.fixture_html(1))
    info = renderer.page.evaluate(
        """() => ({
          brand: document.querySelector('.brand').getBoundingClientRect().left,
          counter: document.querySelector('.counter').getBoundingClientRect().left,
          counterText: document.querySelector('.counter').innerText,
          handle: !!document.querySelector('.handle'),
          heebo: [...document.fonts].some(f => f.family.includes('Heebo')
                                              && f.status === 'loaded'),
        })"""
    )
    assert info["counter"] < info["brand"]
    assert info["counterText"] == "1/3"
    assert info["handle"] is False
    assert info["heebo"] is True


def test_handle_only_on_last_slide(renderer):
    renderer.load(gen.fixture_html(gen.TOTAL))
    text = renderer.page.evaluate("document.querySelector('.handle').innerText")
    assert text == "@the_silver_fox_men"


def test_list_layout_renders_items(renderer):
    renderer.load(gen.fixture_html(2))
    items = renderer.page.evaluate(
        "[...document.querySelectorAll('.items li')].map(li => li.innerText)"
    )
    assert items == gen.FIXTURES[1][1].items


def test_user_text_is_escaped():
    gen.ensure_background()
    slide = Slide(background=gen.BG, title="<b>x</b> & $css ${brand}")
    doc = render.build_html(slide, 1, 2, root=gen.ROOT)
    assert "&lt;b&gt;x&lt;/b&gt; &amp; $css ${brand}" in doc


def test_render_post_writes_valid_jpegs(renderer, tmp_path):
    gen.ensure_background()
    post = Post(
        id="2026-09-25-render",
        publish_at="2026-09-25 07:00",
        caption="x",
        mode=Mode.render,
        slides=[Slide(background=gen.BG, title="אחת"), Slide(background=gen.BG, title="שתיים")],
    )
    slides_dir = tmp_path / "slides"
    slides_dir.mkdir()
    (slides_dir / "7.jpg").write_bytes(b"stale")  # left over from a longer post
    paths = render.render_post(post, tmp_path, root=gen.ROOT, renderer=renderer)
    assert [p.name for p in paths] == ["1.jpg", "2.jpg"]
    assert validate_slides(slides_dir) == []
    with Image.open(paths[0]) as im:
        assert im.size == (SLIDE_W, SLIDE_H) and im.mode == "RGB"


def hot_pixels(a: Image.Image, b: Image.Image) -> tuple[int, Image.Image]:
    """Count pixels whose max channel difference exceeds the threshold."""
    size = (SLIDE_W // SCALE, SLIDE_H // SCALE)

    def norm(im: Image.Image) -> Image.Image:
        return im.convert("RGB").resize(size, Image.BOX).filter(ImageFilter.GaussianBlur(1))

    r, g, b_ = ImageChops.difference(norm(a), norm(b)).split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), b_)
    hot = sum(1 for v in worst.getdata() if v > PIXEL_THRESHOLD)
    return hot, worst.point(lambda v: 255 if v > PIXEL_THRESHOLD else v * 4)


def test_hot_pixel_metric_catches_a_moved_period():
    # Guard the metric itself: a 12px dot moved 200px must fail, AA noise must not.
    base = Image.new("RGB", (SLIDE_W, SLIDE_H), (30, 34, 42))
    moved = base.copy()
    base.paste((255, 255, 255), (300, 900, 312, 912))
    moved.paste((255, 255, 255), (500, 900, 512, 912))
    assert hot_pixels(base, moved)[0] > MAX_HOT_PIXELS
    noisy = base.copy()
    noisy.paste((70, 74, 82), (300, 899, 312, 900))  # one faint AA row
    assert hot_pixels(base, noisy)[0] == 0


@pytest.mark.skipif(
    sys.platform != "linux" and os.environ.get("DOXA_GOLDEN") != "1",
    reason="pixel goldens are Linux/Chromium renders; bidi geometry tests cover other OSes",
)
@pytest.mark.parametrize("name", [name for name, _ in gen.FIXTURES])
def test_golden_matches(renderer, name: str) -> None:
    golden_file = gen.golden_path(name)
    if not golden_file.exists():
        if gen.REGENERATE.exists():
            pytest.skip("goldens are being regenerated by the goldens workflow")
        pytest.fail(f"missing {golden_file.name}: commit tests/golden/REGENERATE to create it")
    rendered = gen.render_fixture(renderer, name)
    with Image.open(golden_file) as golden:
        hot, diff_img = hot_pixels(rendered, golden)
    if hot > MAX_HOT_PIXELS:
        OUT.mkdir(exist_ok=True)
        rendered.save(OUT / f"{name}.actual.png")
        diff_img.save(OUT / f"{name}.diff.png")
    assert hot <= MAX_HOT_PIXELS, f"{name}: {hot} pixels differ by > {PIXEL_THRESHOLD}"
