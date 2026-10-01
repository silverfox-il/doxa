"""Automatic content rules, checked before any post can be approved or published.

Two severities:

* ``block`` — the post is invalid (``doxa validate`` fails, nothing publishes).
* ``review`` — the post may be fine, but a human must look: auto-approve skips it.

Rule sources:

* ``config/rules.yaml`` (public): banned words, review words, dashes, ages,
  hashtags. Generic, no personal data.
* ``rules_private.yaml`` next to the book (private repo): identity terms (the
  owner's real name, city, job) that must never appear. Kept out of this public
  repo on purpose.

The verbatim rule needs the book text (:mod:`doxa.book`). Without it the check
cannot run, which is itself a ``review`` finding, so nothing is auto-approved
blind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .book import Book
from .queue import Mode, Post

BLOCK = "block"
REVIEW = "review"

HEB = "א-ת"
# Hebrew one-letter prefixes (ו ה ב ל מ ש כ) can stack: "ובספר", "שהספר".
PREFIX = "[ובהלמשכ]{0,3}"
# Hyphen-minus, en/em dashes, figure dash, horizontal bar, Hebrew maqaf.
DASHES = re.compile("[-‐‑‒–—―־]")
AGE_RE = re.compile(r"(?:בת|בנות)\s+(\d{2})")


@dataclass
class Finding:
    severity: str
    rule: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.rule} @ {self.where}: {self.detail}"


@dataclass
class RulesConfig:
    block_words: list[str] = field(default_factory=list)
    review_words: list[str] = field(default_factory=list)
    identity_words: list[str] = field(default_factory=list)
    blocked_hashtags: list[str] = field(default_factory=list)
    signature: str = "אתה צריך להיות הסיבה – לא האפקט"
    min_woman_age: int = 37

    @classmethod
    def load(cls, public: Path, private: Path | None = None) -> RulesConfig:
        data = yaml.safe_load(public.read_text(encoding="utf-8")) or {}
        cfg = cls(**data)
        if private is not None and private.is_file():
            extra = yaml.safe_load(private.read_text(encoding="utf-8")) or {}
            cfg.identity_words += list(extra.get("identity_words", []))
            cfg.block_words += list(extra.get("block_words", []))
        return cfg


def _word_re(word: str) -> re.Pattern[str]:
    """Match ``word`` as a whole Hebrew/Latin word, allowing Hebrew prefixes."""
    w = re.escape(word)
    if re.match(f"[{HEB}]", word):
        return re.compile(f"(?<![{HEB}]){PREFIX}{w}(?![{HEB}])")
    return re.compile(rf"(?<!\w){w}(?!\w)", re.IGNORECASE)


def post_texts(post: Post) -> list[tuple[str, str]]:
    """(where, text) for every piece of text a viewer will read."""
    out: list[tuple[str, str]] = []
    for i, s in enumerate(post.slides, start=1):
        for name in ("kicker", "title", "accent", "body"):
            text = getattr(s, name)
            if text:
                out.append((f"slide {i} {name}", text))
        for j, item in enumerate(s.items, start=1):
            out.append((f"slide {i} item {j}", item))
    if post.reel is not None:
        for i, line in enumerate(post.reel.lines, start=1):
            out.append((f"reel line {i}", line))
    for i, text in enumerate(caption_lines(post.caption), start=1):
        out.append((f"caption line {i}", text))
    return out


def caption_lines(caption: str) -> list[str]:
    """Caption text lines, without the dot spacer and the hashtag block."""
    lines = []
    for line in caption.splitlines():
        s = line.strip()
        if not s or s == "." or all(tok.startswith("#") for tok in s.split()):
            continue
        lines.append(s)
    return lines


def hashtags(caption: str) -> list[str]:
    return re.findall(r"#[\w]+", caption)


def check_post(post: Post, cfg: RulesConfig, book: Book | None) -> list[Finding]:
    findings: list[Finding] = []
    texts = post_texts(post)

    def add(sev: str, rule: str, where: str, detail: str) -> None:
        findings.append(Finding(sev, rule, where, detail))

    for where, text in texts:
        # Verbatim: every visible text must be cut from the book, word for word.
        if post.mode != Mode.prebuilt or where.startswith("caption"):
            if book is None:
                add(REVIEW, "verbatim", where, "book not available, cannot verify")
            elif not book.contains(text):
                add(BLOCK, "verbatim", where, f"not found word for word in the book: {text[:60]!r}")

        stripped = text.replace(cfg.signature, "")
        if DASHES.search(stripped):
            add(BLOCK, "no-dashes", where, f"dash in {text[:60]!r}")
        for word in cfg.block_words:
            if _word_re(word).search(text):
                add(BLOCK, "banned-word", where, f"{word!r}")
        for word in cfg.identity_words:
            if _word_re(word).search(text):
                add(BLOCK, "identity", where, "identifying detail about the owner")
        for word in cfg.review_words:
            if _word_re(word).search(text):
                add(REVIEW, "sensitive", where, f"{word!r} needs a human look")
        for m in AGE_RE.finditer(text):
            if int(m.group(1)) < cfg.min_woman_age:
                add(BLOCK, "ages", where, f"{m.group(0)!r} is below {cfg.min_woman_age}")

    if post.mode == Mode.prebuilt:
        add(REVIEW, "prebuilt", "slides", "text inside prebuilt images cannot be checked")
    for tag in hashtags(post.caption):
        if tag.lstrip("#") in cfg.blocked_hashtags:
            add(BLOCK, "hashtag", "caption", f"{tag} is not allowed")
    return findings


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == BLOCK]


def load_context(root: Path) -> tuple[RulesConfig, Book | None]:
    """Rules config (public + private) and the book, as available on this machine."""
    from .book import find_book_dir

    book_dir = find_book_dir(root)
    private = book_dir.parent / "rules_private.yaml" if book_dir else None
    public = root / "config" / "rules.yaml"
    if not public.is_file():  # a --root without its own config uses this repo's
        public = Path(__file__).resolve().parent.parent / "config" / "rules.yaml"
    cfg = RulesConfig.load(public, private)
    return cfg, (Book.load(book_dir) if book_dir else None)
