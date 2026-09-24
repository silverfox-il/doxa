"""Slide renderer (spec §3).

``mode: render`` fills ``templates/slide.html`` (RTL Hebrew, embedded Heebo
font) for each slide and screenshots it to a 1080x1350 JPEG with Chromium via
Playwright. ``mode: prebuilt`` posts are never rendered, only validated (see
:mod:`doxa.slides`).

The HTML is built deterministically (no timestamps, no network: font and
background are inlined as data URIs) so golden visual tests are stable for a
pinned Chromium build.
"""

from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path
from string import Template

from . import IG_HANDLE
from .queue import Layout, Mode, Post, Slide
from .slides import SLIDE_H, SLIDE_W

JPEG_QUALITY = 90
BRAND = "סילבר פוקס"

# Repo root = parent of the doxa package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
FONTS_DIR = REPO_ROOT / "assets" / "fonts"

# Single Heebo variable font (OFL) covering weights 100-900. Committed under
# assets/fonts/ so rendering never touches the network.
FONT_FILE = "Heebo[wght].ttf"


class RenderError(Exception):
    pass


@lru_cache(maxsize=1)
def _font_faces() -> str:
    """@font-face embedding the Heebo variable font as a data URI."""
    path = FONTS_DIR / FONT_FILE
    if not path.exists():
        raise RenderError(f"missing font {path} — commit Heebo to assets/fonts/")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        "@font-face{font-family:'Heebo';font-style:normal;"
        "font-weight:100 900;font-display:block;"
        f"src:url(data:font/ttf;base64,{b64}) format('truetype');}}"
    )


@lru_cache(maxsize=1)
def _template() -> Template:
    path = TEMPLATES_DIR / "slide.html"
    if not path.exists():
        raise RenderError(f"missing template {path}")
    return Template(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _css() -> str:
    path = TEMPLATES_DIR / "style.css"
    if not path.exists():
        raise RenderError(f"missing stylesheet {path}")
    return path.read_text(encoding="utf-8")


def _bg_data_uri(background: str, root: Path) -> str:
    """Embed the background photo as a data URI (keeps render offline)."""
    path = root / background
    if not path.is_file():
        raise RenderError(f"background not found: {background}")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _content_html(slide: Slide) -> str:
    parts: list[str] = []
    if slide.kicker:
        parts.append(f'<div class="kicker">{html.escape(slide.kicker)}</div>')
    if slide.title:
        parts.append(f'<div class="title">{html.escape(slide.title)}</div>')
    if slide.accent:
        parts.append(f'<div class="accent">{html.escape(slide.accent)}</div>')
    if slide.layout == Layout.list:
        lis = "".join(f"<li>{html.escape(item)}</li>" for item in slide.items)
        parts.append(f'<ul class="items">{lis}</ul>')
    if slide.body:
        parts.append(f'<div class="body">{html.escape(slide.body)}</div>')
    return "\n".join(f"    {p}" for p in parts)


def build_html(slide: Slide, index: int, total: int, *, root: Path = REPO_ROOT) -> str:
    """Full HTML document for one slide. ``index`` is 1-based."""
    is_last = index == total
    handle = f'  <div class="handle">{html.escape(IG_HANDLE)}</div>' if is_last else ""
    # $-placeholders are filled once; values are never re-scanned, so a "$" in
    # user text cannot inject another placeholder.
    return _template().substitute(
        font_faces=_font_faces(),
        css=_css(),
        background=_bg_data_uri(slide.background, root),
        brand=html.escape(BRAND),
        counter=f"{index}/{total}",
        layout=slide.layout.value,
        content=_content_html(slide),
        handle=handle,
    )


class Renderer:
    """One headless Chromium reused for many slides. Use as a context manager."""

    def __enter__(self) -> Renderer:
        # Imported lazily so validate/status work without a browser installed.
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=["--force-color-profile=srgb"])
        self.page = self._browser.new_page(
            viewport={"width": SLIDE_W, "height": SLIDE_H}, device_scale_factor=1
        )
        return self

    def __exit__(self, *exc: object) -> None:
        self._browser.close()
        self._pw.stop()

    def load(self, doc: str) -> None:
        self.page.set_content(doc, wait_until="load")
        # Font is a data URI with font-display:block; wait so text never
        # renders in a fallback face.
        self.page.evaluate("document.fonts.ready")

    def screenshot(self, doc: str, *, fmt: str = "jpeg") -> bytes:
        self.load(doc)
        clip = {"x": 0, "y": 0, "width": SLIDE_W, "height": SLIDE_H}
        if fmt == "jpeg":
            return self.page.screenshot(type="jpeg", quality=JPEG_QUALITY, clip=clip)
        return self.page.screenshot(type="png", clip=clip)


def render_post(
    post: Post,
    post_dir: Path,
    *,
    root: Path = REPO_ROOT,
    renderer: Renderer | None = None,
) -> list[Path]:
    """Render every slide of a ``mode: render`` post to ``slides/1.jpg..N.jpg``.

    Stale slides from a previous, longer render are removed so the directory
    always holds exactly N files. Pass ``renderer`` to reuse an open browser.
    """
    if post.mode != Mode.render:
        raise RenderError(f"render_post called on mode={post.mode.value}")

    slides_dir = post_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    total = len(post.slides)
    for old in slides_dir.glob("*.jpg"):
        if not (old.stem.isdigit() and 1 <= int(old.stem) <= total):
            old.unlink()

    docs = [build_html(s, i, total, root=root) for i, s in enumerate(post.slides, start=1)]
    if renderer is None:
        with Renderer() as r:
            return render_post(post, post_dir, root=root, renderer=r)

    out_paths: list[Path] = []
    for i, doc in enumerate(docs, start=1):
        out = slides_dir / f"{i}.jpg"
        out.write_bytes(renderer.screenshot(doc))
        out_paths.append(out)
    return out_paths
