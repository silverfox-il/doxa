"""Carousel formats: the HTML each one builds (no browser needed)."""

from __future__ import annotations

from doxa import render
from doxa.queue import Format, Slide

from .golden.gen import BG, ROOT


def test_photo_hook_slide_has_bg_swipe_and_hook_class():
    doc = render.build_html(Slide(background=BG, title="א ב ג"), 1, 3, root=ROOT)
    assert 'class="slide fmt-photo hook"' in doc
    assert '<img class="bg"' in doc and 'class="swipe"' in doc
    assert 'class="handle"' not in doc


def test_tweet_card_has_name_handle_and_no_photo():
    doc = render.build_html(Slide(title="א ב ג"), 3, 3, root=ROOT, look=Format.tweet)
    assert 'class="slide fmt-tweet last"' in doc
    assert 'class="card"' in doc and "@the_silver_fox_men" in doc and "<svg" in doc
    assert '<img class="bg"' not in doc and 'class="swipe"' not in doc


def test_bold_has_no_photo():
    doc = render.build_html(Slide(title="א ב ג"), 2, 3, root=ROOT, look=Format.bold)
    assert 'class="slide fmt-bold"' in doc and '<img class="bg"' not in doc


def test_user_text_is_escaped():
    doc = render.build_html(Slide(title="<b>$x</b>"), 1, 2, root=ROOT, look=Format.bold)
    assert "&lt;b&gt;$x&lt;/b&gt;" in doc


def test_center_layout_is_available_for_photo():
    from doxa.queue import Layout

    doc = render.build_html(Slide(background=BG, title="א ב ג", layout=Layout.center), 2, 3,
                            root=ROOT)
    assert 'class="content center"' in doc
