"""Content rules (doxa/rules.py) and the verbatim book check (doxa/book.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from doxa import rules
from doxa.book import Book, find_book_dir, normalize
from doxa.cli import main
from doxa.queue import Post, Status

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
# The verbatim tests below run in word-for-word mode; VOICE is the live config.
VOICE = rules.RulesConfig.load(Path(__file__).resolve().parent.parent / "config" / "rules.yaml")
CFG.require_verbatim = True
CFG.style_rules = []  # style has its own tests below, on VOICE


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
    book_re = rules._word_re(next(w for w in CFG.block_words if "ספר" in w))
    for blocked in ("הספר הזה", "בספר", "שבספר", "ספרים", "והספרים"):
        assert book_re.search(blocked), blocked
    for legal in ("מספרים", "לספר לך", "מספר עליך", "סיפור"):
        assert not book_re.search(legal), legal


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
        caption="תפטר את הבוס שלך.",
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


def test_a_quote_may_be_used_once(repo):
    line = "הוא לא עושה שום דבר לא בסדר."
    a = render_post_data(
        "2026-10-03-a",
        caption=line,
        slides=[{"background": "assets/backgrounds/bg.jpg", "title": line}] * 2,
    )
    b = render_post_data(
        "2026-10-04-b",
        publish_at="2026-10-04 07:30",
        caption="תזכור:",
        slides=[
            {"background": "assets/backgrounds/bg.jpg", "title": "תזכור:"},
            {"background": "assets/backgrounds/bg.jpg", "title": line},
        ],
    )
    write_post(repo, a)
    write_post(repo, b)
    result = CliRunner().invoke(main, ["--root", str(repo), "validate"])
    assert result.exit_code == 1
    assert "repeat @ 2026-10-04-b: already used in 2026-10-03-a" in result.output
    assert "2026-10-03-a: already" not in result.output  # same post twice is fine
    used = CliRunner().invoke(main, ["--root", str(repo), "used"])
    assert used.exit_code == 0
    text = (repo / "content" / "used.yaml").read_text(encoding="utf-8")
    assert "2026-10-03-a" in text and line in text and "תזכור:" not in text


# --- content engine: hook, call to action, pillar ----------------------------------

CTA = CFG.cta[0]
ENGINE_AT = "2026-10-05 13:00"


def engine_post(*titles: str, caption: str | None = None, **kw) -> Post:
    hook = titles[0]
    caption = caption if caption is not None else f"{hook}\n\n{CTA}\n.\n#גרושים"
    slides = [{"title": t} for t in titles]
    data = render_post_data(caption=caption, slides=slides, publish_at=ENGINE_AT, format="bold")
    data.setdefault("pillar", "dating")
    data.update(kw)
    return Post.model_validate(data)


def engine_found(post: Post, book: Book) -> list[tuple[str, str]]:
    return [(s, r) for s, r in found(post, book) if r in {"hook", "cta", "pillar"}]


def test_cta_list_is_loaded_and_clean():
    assert 5 <= len(CFG.cta) <= 10
    for line in CFG.cta:
        assert not rules.DASHES.search(line), line


def test_engine_post_with_hook_cta_pillar_passes(book):
    post = engine_post("הוא פשוט לא מדליק.", "נחמד זה לא תכונה, זה הדבר")
    assert found(post, book) == []


def test_cta_line_is_exempt_from_verbatim_only_if_whitelisted(book):
    post = engine_post(
        "הוא פשוט לא מדליק.",
        "נחמד זה לא תכונה, זה הדבר",
        caption="הוא פשוט לא מדליק.\n\nתעקוב אחריי עכשיו.\n.\n#גרושים",
    )
    got = found(post, book)
    assert ("block", "verbatim") in got and ("block", "cta") in got


def test_two_ctas_block(book):
    post = engine_post(
        "הוא פשוט לא מדליק.",
        "נחמד זה לא תכונה, זה הדבר",
        caption=f"הוא פשוט לא מדליק.\n{CFG.cta[0]}\n{CFG.cta[1]}\n.\n#גרושים",
    )
    assert ("block", "cta") in engine_found(post, book)


def test_long_hook_blocks(book):
    long_hook = "הוא לא עושה שום דבר לא בסדר. הוא פשוט לא מדליק. נחמד זה לא תכונה, זה הדבר"
    post = engine_post(long_hook, "נחמד זה לא תכונה, זה הדבר")
    assert ("block", "hook") in engine_found(post, book)


def test_connector_hook_blocks(book):
    post = engine_post("הוא פשוט", "נחמד זה לא תכונה, זה הדבר")
    assert ("block", "hook") in engine_found(post, book)


def test_caption_must_open_with_hook(book):
    post = engine_post(
        "הוא פשוט לא מדליק.",
        "נחמד זה לא תכונה, זה הדבר",
        caption=f"נחמד זה לא תכונה, זה הדבר\n\n{CTA}\n.\n#גרושים",
    )
    assert ("block", "hook") in engine_found(post, book)


def test_reel_hook_is_line_one(book):
    reel = {"lines": ["הוא", "פשוט לא מדליק."], "music": "a.mp3", "per_line": 4, "hold": 7}
    post = engine_post(
        "x", mode="reel", slides=[], reel=reel, format=None, caption=f"הוא\n\n{CTA}\n.\n#גרושים"
    )
    assert ("block", "hook") in engine_found(post, book)


def test_missing_pillar_blocks(book):
    post = engine_post("הוא פשוט לא מדליק.", "נחמד זה לא תכונה, זה הדבר", pillar=None)
    assert ("block", "pillar") in engine_found(post, book)


def test_old_posts_are_not_bound_by_engine_rules(book):
    post = post_with("הוא פשוט לא מדליק.", "נחמד זה לא תכונה, זה הדבר")
    assert post.publish_at < CFG.engine_from
    assert found(post, book) == []


def test_pillar_rotation_blocks_two_in_a_row():
    def p(pid, at, pillar):
        return engine_post("הוא פשוט לא מדליק.", "נחמד", id=pid, publish_at=at, pillar=pillar)

    ok = [
        p("2026-10-05-a", "2026-10-05 13:00", "body"),
        p("2026-10-05-b", "2026-10-05 20:00", "mind"),
    ]
    assert rules.pillar_rotation(ok, CFG) == []
    bad = ok + [p("2026-10-06-c", "2026-10-06 13:00", "mind")]
    got = rules.pillar_rotation(bad, CFG)
    assert [f.where for f in got] == ["2026-10-06-c"]
    # Order is by publish time, not by list order.
    assert rules.pillar_rotation(list(reversed(ok)), CFG) == []


def test_cta_lines_may_repeat_across_posts():
    a = engine_post("הוא פשוט לא מדליק.", "נחמד", id="2026-10-05-a")
    b = engine_post("נחמד זה לא תכונה, זה הדבר", "המינימלי", id="2026-10-05-b")
    assert rules.repeated_quotes([a, b], CFG.cta) == []
    assert rules.repeated_quotes([a, b]) != []


# --- book voice (live config): own words allowed, crude words masked --------------


def voice(*titles: str) -> list[tuple[str, str]]:
    post = post_with(*titles, caption=f"{titles[0]}\n.\n#גרושים")
    return [(f.severity, f.rule) for f in rules.check_post(post, VOICE, None)]


def test_live_config_is_book_voice_not_verbatim():
    assert VOICE.require_verbatim is False
    assert voice("אם אתה מחכה לאישור, כבר הפסדת.", "תפסיק לבקש, תתחיל להחליט.") == []


@pytest.mark.parametrize(
    "raw",
    [
        "היא לא זונה.",
        "כל הזונות האלה",
        "הוא רק רוצה לזיין",
        "הוא מזדיין איתה",
        "זיון אחד",
        "תחשוב עם הזין",
        "סקס טוב",
        "בלי אורגזמה",
        "שרמוטה",
        "כוסית",
    ],
)
def test_raw_crude_words_block(raw):
    assert ("block", "masked-word") in voice(raw, "תפסיק לבקש, תתחיל להחליט.")


@pytest.mark.parametrize(
    "masked",
    [
        "היא לא Zונה.",
        "הוא רק רוצה לעשות את המעשה",
        "תחשוב עם הZין",
        "Sקס טוב",
        "בלי אורגZמה",
        "שרמו*ה",
        "Kוסית",
    ],
)
def test_masked_forms_pass(masked):
    assert voice(masked, "תפסיק לבקש, תתחיל להחליט.") == []


@pytest.mark.parametrize("innocent", ["הוא משלם מזונות כל חודש.", "אוכל מזין ושינה", "אישה זיינה"])
def test_innocent_lookalikes_pass(innocent):
    found_rules = [r for _, r in voice(innocent, "תפסיק לבקש, תתחיל להחליט.")]
    if innocent == "אישה זיינה":  # crude past tense: must be masked too
        assert "masked-word" in found_rules
    else:
        assert "masked-word" not in found_rules


def test_masked_word_finding_says_what_to_write():
    post = post_with("כל הזונות האלה", "תפסיק לבקש, תתחיל להחליט.")
    detail = next(f.detail for f in rules.check_post(post, VOICE, None) if f.rule == "masked-word")
    assert "Zונה" in detail


# --- style: talk to him, correct Hebrew ---------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "היא צריכה להיות נדלקת ממך.",
    ],
)
def test_style_rules_block_preaching_and_known_mistakes(bad):
    assert ("block", "style") in voice(bad, "תפסיק לבקש, תתחיל להחליט.")


@pytest.mark.parametrize(
    "good",
    [
        "אם אתה מחכה לאישור, כבר הפסדת.",
        "אם אתה עד כדי כך דפוק שאתה עונה תוך שנייה, היא כבר יודעת.",
        "היא צריכה להידלק ממך.",
        "הוא ישב מול גבר זר בבר.",
    ],
)
def test_style_rules_allow_second_person(good):
    assert voice(good, "תפסיק לבקש, תתחיל להחליט.") == []


def test_style_rules_skip_published_posts():
    post = post_with("גבר שמחכה לאישור כבר הפסיד.", "תפסיק לבקש, תתחיל להחליט.")
    post = post.model_copy(update={"status": Status.published})
    assert "style" not in [f.rule for f in rules.check_post(post, VOICE, None)]


def test_cta_rotation_blocks_same_cta_twice_in_a_row():
    def p(pid, at, cta):
        caption = f"הוא פשוט לא מדליק.\n\n{cta}\n.\n#גרושים"
        return engine_post("הוא פשוט לא מדליק.", "נחמד", id=pid, publish_at=at, caption=caption)

    a = p("2026-10-05-a", "2026-10-05 13:00", CFG.cta[0])
    b = p("2026-10-05-b", "2026-10-05 20:00", CFG.cta[1])
    c = p("2026-10-06-c", "2026-10-06 13:00", CFG.cta[1])
    assert rules.cta_rotation([a, b], CFG) == []
    assert [f.where for f in rules.cta_rotation([c, a, b], CFG)] == ["2026-10-06-c"]


def test_tease_series_may_generalize_about_women_regular_posts_may_not():
    from doxa.queue import Post

    from .conftest import render_post_data

    line = "כל הנשים בדייטים מחפשות את אותו דבר."
    reel = {"lines": [line, "פלקס אדיר."], "music": "a.mp3", "per_line": 4, "hold": 7}
    plain = Post.model_validate(render_post_data(mode="reel", slides=[], reel=reel))
    tease = Post.model_validate(
        render_post_data(mode="reel", slides=[], reel={**reel, "stories": ["שני"]})
    )
    assert "sensitive" in [f.rule for f in rules.check_post(plain, VOICE, None)]
    assert "sensitive" not in [f.rule for f in rules.check_post(tease, VOICE, None)]
    slur = Post.model_validate(
        render_post_data(
            mode="reel", slides=[], reel={**reel, "lines": ["היא כלבה.", "ב"], "stories": ["שני"]}
        )
    )
    assert "sensitive" in [f.rule for f in rules.check_post(slur, VOICE, None)]


def test_third_person_men_allowed_everywhere():
    # Posts quote the owner's book, which talks about men in the third person.
    line = "גבר שיש לו חיים, חברים, תחביבים, הוא גבר שאישה משקיעה בו."
    assert "style" not in [r for _, r in voice(line, "תפסיק לבקש, תתחיל להחליט.")]
