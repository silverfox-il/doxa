"""Instagram stories: the daily teaser series.

The Instagram API cannot add a link sticker or a "share post" card to a story,
so the owner shares regular posts to his story himself, from the app (that card
links to the post). The system publishes stories automatically only for a
teaser series: a reel with ``reel.stories``. Story 1 is the reel video itself
(the reel is also a feed post, which brings the traffic), then
``series/1.jpg..N.jpg``, one image per follow-up text; the last one carries a
banner that points to the profile (tap the name at the top).

``post_story_html`` / ``reel_story_html`` are kept for previews only.

Rendered with Chromium like the slides, so Hebrew is shaped and laid out RTL.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from . import IG_HANDLE
from .queue import Mode, Post
from .render import JPEG_QUALITY, _font_faces

STORY_NAME = "story.jpg"
SERIES_DIR = "series"
STORY_W, STORY_H = 1080, 1920

BANNER_POST = "פוסט חדש בפרופיל"
BANNER_REEL = "רילס חדש בפרופיל"
BANNER_MORE = "ההמשך בפרופיל"
BANNER_HINT = "↖ לחיצה על השם למעלה"

_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px}
body{font-family:'Heebo',sans-serif;direction:rtl;color:#fff;background:#141414;
  position:relative;overflow:hidden}
.bg{position:absolute;inset:-60px;width:1200px;height:2040px;object-fit:cover;
  filter:blur(38px) brightness(.42)}
.card{position:absolute;left:90px;right:90px;top:430px;border-radius:36px;
  overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.55)}
.card img{display:block;width:100%}
.banner{position:absolute;top:200px;left:60px;display:flex;
  flex-direction:column;align-items:flex-end;gap:14px}
.chip{background:#ff6a13;color:#141414;font-weight:900;font-size:54px;
  padding:16px 34px;border-radius:999px}
.hint{font-size:36px;font-weight:600;color:#fff;opacity:.9;padding-right:8px}
.text{position:absolute;left:100px;right:100px;top:50%;transform:translateY(-50%);
  text-align:center;font-weight:900;line-height:1.18;white-space:pre-line}
.hook{font-size:84px}
.series{font-size:88px}
.counter{position:absolute;top:210px;right:80px;font-size:40px;font-weight:800;
  direction:ltr;opacity:.85}
.handle{position:absolute;bottom:150px;left:0;right:0;text-align:center;
  font-size:38px;font-weight:700;direction:ltr;color:#ff6a13}
.accent{background:#ff6a13;color:#141414}
.accent .handle{color:#141414}
"""


def _doc(body: str, body_class: str = "") -> str:
    return (
        "<!DOCTYPE html><html dir='rtl' lang='he'><head><meta charset='utf-8'>"
        f"<style>{_font_faces()}{_CSS}</style></head>"
        f"<body class='{body_class}'>{body}"
        f"<div class='handle'>{html.escape(IG_HANDLE)}</div></body></html>"
    )


def _banner(label: str) -> str:
    return (
        f"<div class='banner'><div class='chip'>{html.escape(label)}</div>"
        f"<div class='hint'>{html.escape(BANNER_HINT)}</div></div>"
    )


def post_story_html(slide1: bytes) -> str:
    uri = "data:image/jpeg;base64," + base64.b64encode(slide1).decode("ascii")
    return _doc(
        f"<img class='bg' src='{uri}' alt=''><div class='card'><img src='{uri}' alt=''></div>"
        + _banner(BANNER_POST)
    )


def reel_story_html(hook: str) -> str:
    return _doc(f"<div class='text hook'>{html.escape(hook)}</div>" + _banner(BANNER_REEL))


def series_html(text: str, index: int, total: int) -> str:
    """Follow-up story ``index`` (2..total; story 1 is the reel video)."""
    last = index == total
    body = (
        f"<div class='counter'>{index}/{total}</div>"
        f"<div class='text series'>{html.escape(text)}</div>"
    )
    if last:
        body += _banner(BANNER_MORE)
    return _doc(body, "accent" if index % 2 == 0 else "")


def story_docs(post: Post, post_dir: Path) -> list[tuple[Path, str]]:
    """(output path, HTML) for every story image this post needs."""
    if post.mode == Mode.reel and post.reel is not None and post.reel.stories:
        total = len(post.reel.stories) + 1
        return [
            (post_dir / SERIES_DIR / f"{i}.jpg", series_html(text, i + 1, total))
            for i, text in enumerate(post.reel.stories, start=1)
        ]
    return []


def render_stories(post: Post, post_dir: Path) -> list[Path]:
    """Render this post's story images; remove stale ones. Returns the paths."""
    from playwright.sync_api import sync_playwright

    docs = story_docs(post, post_dir)
    keep = {p for p, _ in docs}
    stale = [post_dir / STORY_NAME, *sorted((post_dir / SERIES_DIR).glob("*.jpg"))]
    for old in stale:
        if old.is_file() and old not in keep:
            old.unlink()
    if not docs:
        return []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])
        try:
            page = browser.new_page(viewport={"width": STORY_W, "height": STORY_H})
            for out, doc in docs:
                out.parent.mkdir(parents=True, exist_ok=True)
                page.set_content(doc, wait_until="load")
                page.evaluate("document.fonts.ready")
                out.write_bytes(page.screenshot(type="jpeg", quality=JPEG_QUALITY))
        finally:
            browser.close()
    return [p for p, _ in docs]


def story_files(post: Post, post_dir: Path) -> list[str]:
    """Names (inside ``queue/<id>/``) to share as stories, in order.

    Only a teaser series has any: the reel video, then its follow-up images.
    Regular posts get none; the owner shares them himself.
    """
    if post.mode == Mode.reel and post.reel is not None and post.reel.stories:
        series = [
            f"{SERIES_DIR}/{i}.jpg"
            for i in range(1, len(post.reel.stories) + 1)
            if (post_dir / SERIES_DIR / f"{i}.jpg").is_file()
        ]
        return ["reel.mp4", *series]
    return []
