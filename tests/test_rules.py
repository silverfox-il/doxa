"""Content rules (doxa/rules.py) and the verbatim book check (doxa/book.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from doxa import rules
from doxa.book import Book, find_book_dir, normalize
from doxa.cli import main
from doxa.queue import Post

from .conftest import render_post_data, write_post

BOOK_TEXT = """# 2. פרק

### הנחמד מפסיד, תמיד

הוא לא עושה שום דבר לא בסדר. הוא פשוט לא מדליק. נחמד זה לא תכונה, זה הדבר
המינימלי שמצפים ממך, כמו לא לאחר ולא להריח רע.

אתה צריך להיות הסיבה – לא האפקט.

גבר בן 45 יכול לצאת עם נשים מגיל 37 בערך. היא הייתה בת 30 אז.

הספר הזה לא נכתב בשביל בחורים בני 25. בגיל ה־20 הכל אחרת.

הדייט הראשון שלך לא יהיה במסעדה יקרה. תפטר את הבוס שלך. ספרו לי על אפי.
"""

CFG = rules.RulesConfig.load(Path(__file__).resolve().parent.parent / "config" / "rules.yaml")
CFG.identity_words = ["אפי"]


@pytest.fixture
def book(tmp_path) -> Book:
    d = tmp_path / "book"
    d.mkdir()
    (d / "02.md").write_text(BOOK_TEXT, encoding="utf-8")
    return Book.load(d)


def post_with(*titles: str, caption: str = "הוא פשוט לא מדליק.\n.\n#גרושים") -> Post:
    slides = [{"background": "assets/backgrounds/bg.jpg", "title": t} for t in titles]
    return Post.model_validate(render_post_data(caption=caption, slides=slides))


def found(post: Post, book: Book | None) -> list[tuple[str, str]]:
    return [(f.severity, f.rule) for f in rules.check_post(post, CFG, book)]


# --- verbatim -------------------------------------------------------------------


def test_verbatim_quotes_pass_even_across_line_breaks(book):
    post = post_with("הוא לא עושה שום דבר לא בסדר.", "נחמד זה לא תכונה, זה הדבר\nהמינימלי")
    assert found(post, book) == []


def test_reworded_text_is_blocked(book):
    post = post_with("הוא לא עושה שום דבר רע.", "הוא פשוט לא מדליק.")
    assert ("block", "verbatim") in found(post, book)


def test_caption_hashtags_and_dot_are_not_quotes(book):
    assert found(post_with("הוא פשוט לא מדליק.", "הוא פשוט לא מדליק."), book) == []
    bad = post_with(
        "הוא פשוט לא מדליק.", "הוא פשוט לא מדליק.", caption="עקוב אחרי העמוד\n.\n#גרושים"
    )
    assert ("block", "verbatim") in found(bad, book)


def test_without_the_book_verbatim_is_a_review_item():
    assert set(found(post_with("הוא פשוט לא מדליק.", "הוא פשוט לא מדליק."), None)) == {
        ("review", "verbatim")
    }


def test_normalize_and_find_book_dir(tmp_path, monkeypatch):
    assert normalize("  א\n\nב \t ג ") == "א ב ג"
    monkeypatch.delenv("DOXA_BOOK_DIR", raising=False)
    assert find_book_dir(tmp_path) is None
    (tmp_path / "private" / "book").mkdir(parents=True)
    (tmp_path / "private" / "book" / "01.md").write_text("x", encoding="utf-8")
    assert find_book_dir(tmp_path) == tmp_path / "private" / "book"


def test_raw_old_edition_txt_never_proves_a_quote(tmp_path):
    d = tmp_path / "book"
    (d / "old").mkdir(parents=True)
    (d / "01.md").write_text("משהו אחר", encoding="utf-8")
    (d / "old" / "ch2.txt").write_text("משפט מהמהדורה הישנה", encoding="utf-8")
    assert not Book.load(d).contains("משפט מהמהדורה הישנה")
    (d / "old_clean").mkdir()
    (d / "old_clean" / "ch2.md").write_text("משפט מהמהדורה הישנה", encoding="utf-8")
    assert Book.load(d).contains("משפט מהמהדורה הישנה")


# --- hard rules -------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,rule",
    [
        ("הספר הזה לא נכתב בשביל בחורים בני 25.", "banned-word"),
        ("תפטר את הבוס שלך.", "banned-word"),
        ("ספרו לי על אפי.", "identity"),
        ("בגיל ה־20 הכל אחרת.", "no-dashes"),
        ("היא הייתה בת 30 אז.", "ages"),
    ],
)
def test_hard_rules_block(book, title, rule):
    assert ("block", rule) in found(post_with(title, "הוא פשוט לא מדליק."), book)


def test_signature_is_the_only_dash_allowed(book):
    assert found(post_with("אתה צריך להיות הסיבה – לא האפקט.", "הוא פשוט לא מדליק."), book) == []


def test_allowed_age_passes(book):
    post = post_with("גבר בן 45 יכול לצאת עם נשים מגיל 37 בערך.", "הוא פשוט לא מדליק.")
    assert found(post, book) == []


def test_sensitive_words_need_review_not_block(book):
    post = post_with("הדייט הראשון שלך לא יהיה במסעדה יקרה.", "הוא פשוט לא מדליק.")
    assert found(post, book) == [("review", "sensitive")]


def test_word_match_respects_hebrew_word_boundaries():
    # "בוס" inside another word is fine; with prefixes it is caught.
    assert not rules._word_re("בוס").search("אוטובוס")
    assert rules._word_re("בוס").search("והבוס שלך")
    assert rules._word_re("ספר").search("שבספר")
    assert not rules._word_re("ספר").search("מספרים")


def test_blocked_hashtag(book):
    post = post_with("הוא פשוט לא מדליק.", "הוא פשוט לא מדליק.", caption="הוא פשוט לא מדליק.\n#ספר")
    assert ("block", "hashtag") in found(post, book)


def test_reel_lines_are_checked(book):
    data = render_post_data(
        mode="reel",
        slides=[],
        caption="הוא פשוט לא מדליק.",
        reel={
            "lines": ["הוא לא עושה שום דבר לא בסדר.", "הוא פשוט מגניב."],
            "music": "a.mp3",
            "per_line": 6,
            "hold": 6,
        },
    )
    assert ("block", "verbatim") in found(Post.model_validate(data), book)


def test_private_rules_file_adds_identity_terms(tmp_path):
    pub = tmp_path / "rules.yaml"
    pub.write_text("block_words: [x]\n", encoding="utf-8")
    priv = tmp_path / "rules_private.yaml"
    priv.write_text("identity_words: [שםפרטי]\n", encoding="utf-8")
    cfg = rules.RulesConfig.load(pub, priv)
    assert cfg.identity_words == ["שםפרטי"] and cfg.block_words == ["x"]


# --- CLI ---------------------------------------------------------------------------


def test_rules_cli_and_validate_block_bad_posts(repo, tmp_path, monkeypatch, book):
    d = tmp_path / "bk"
    d.mkdir()
    (d / "02.md").write_text(BOOK_TEXT, encoding="utf-8")
    monkeypatch.setenv("DOXA_BOOK_DIR", str(d))
    good = render_post_data(
        "2026-10-03-good",
        caption="הוא פשוט לא מדליק.",
        slides=[{"background": "assets/backgrounds/bg.jpg", "title": "הוא פשוט לא מדליק."}] * 2,
    )
    bad = render_post_data(
        "2026-10-04-bad",
        caption="הוא פשוט לא מדליק.",
        slides=[{"background": "assets/backgrounds/bg.jpg", "title": "תפטר את הבוס שלך."}] * 2,
    )
    write_post(repo, good)
    write_post(repo, bad)
    runner = CliRunner()
    out = runner.invoke(main, ["--root", str(repo), "rules"])
    assert out.exit_code == 1
    assert "✓ 2026-10-03-good" in out.output and "✗ 2026-10-04-bad" in out.output
    val = runner.invoke(main, ["--root", str(repo), "validate"])
    assert val.exit_code == 1 and "banned-word" in val.output
    assert "2026-10-03-good" not in val.output
