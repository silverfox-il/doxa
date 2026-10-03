"""Automatic content rules, checked before any post can be approved or published.

Two severities:

* ``block`` — the post is invalid (``doxa validate`` fails, nothing publishes).
* ``review`` — the post may be fine, but a human must look: auto-approve skips it.

Rule sources:

* ``config/rules.yaml`` (public): banned words, review words, dashes, ages,
  hashtags. Generic, no personal data.
* ``config/cta.yaml`` (public, owner-approved): the closed list of call to action
  lines. A caption line that matches one exactly is the only text allowed that
  is not from the book.
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
from .queue import Mode, Post, parse_local

BLOCK = "block"
REVIEW = "review"

HEB = "א-ת"
# Hebrew one-letter prefixes (ו ה ב ל מ ש כ) can stack: "ובספר", "שהספר".
PREFIX = "[ובהלמשכ]{0,3}"
# Hyphen-minus, en/em dashes, figure dash, horizontal bar, Hebrew maqaf.
DASHES = re.compile("[-‐‑‒–—―־]")
AGE_RE = re.compile(r"(?:בת|בנות)\s+(\d{2})")
WORD_RE = re.compile(r"[0-9A-Za-zא-ת]")


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
    # Content engine rules (hook, CTA, pillar) bind posts from this time on;
    # older posts were made before the rules existed.
    engine_from: str = "2026-10-04 00:00"
    hook_min_words: int = 3
    hook_max_words: int = 12
    cta: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, public: Path, private: Path | None = None) -> RulesConfig:
        data = yaml.safe_load(public.read_text(encoding="utf-8")) or {}
        cfg = cls(**data)
        cta_file = public.with_name("cta.yaml")
        if cta_file.is_file():
            cta = yaml.safe_load(cta_file.read_text(encoding="utf-8")) or {}
            cfg.cta = [line.strip() for line in cta.get("lines", [])]
        if private is not None and private.is_file():
            extra = yaml.safe_load(private.read_text(encoding="utf-8")) or {}
            cfg.identity_words += list(extra.get("identity_words", []))
            cfg.block_words += list(extra.get("block_words", []))
        return cfg


def _word_re(word: str) -> re.Pattern[str]:
    """Match ``word`` as a whole Hebrew/Latin word, allowing Hebrew prefixes.

    An entry starting with ``re:`` is used as a raw regular expression, for
    words whose prefixed forms are innocent ("מספר" = number/tells, not "book").
    """
    if word.startswith("re:"):
        return re.compile(word[3:])
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


def word_count(text: str) -> int:
    return sum(1 for tok in text.split() if WORD_RE.search(tok))


def hook_text(post: Post) -> str | None:
    """What the viewer sees first: slide 1's title, or the reel's first line."""
    if post.mode == Mode.render and post.slides:
        return post.slides[0].title
    if post.mode == Mode.reel and post.reel is not None:
        return post.reel.lines[0]
    return None


def is_engine_post(post: Post, cfg: RulesConfig) -> bool:
    return post.publish_at_dt >= parse_local(cfg.engine_from)


def check_post(post: Post, cfg: RulesConfig, book: Book | None) -> list[Finding]:
    findings: list[Finding] = []
    texts = post_texts(post)
    cta = set(cfg.cta)

    def add(sev: str, rule: str, where: str, detail: str) -> None:
        findings.append(Finding(sev, rule, where, detail))

    for where, text in texts:
        is_cta = where.startswith("caption") and text in cta
        # Verbatim: every visible text must be cut from the book, word for word.
        # The one exception is a whitelisted call to action in the caption.
        if is_cta:
            pass
        elif post.mode != Mode.prebuilt or where.startswith("caption"):
            if book is None:
                add(REVIEW, "verbatim", where, "book not available, cannot verify")
            elif not book.contains(text):
                add(BLOCK, "verbatim", where, f"not found word for word in the book: {text[:60]!r}")

        stripped = text.replace(cfg.signature, "")
        if DASHES.search(stripped):
            add(BLOCK, "no-dashes", where, f"dash in {text[:60]!r}")
        for word in cfg.block_words:
            if _word_re(word).search(text):
                add(BLOCK, "banned-word", where, f"{word.removeprefix('re:')!r}")
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
    if is_engine_post(post, cfg):
        findings += _engine_findings(post, cfg)
    for tag in hashtags(post.caption):
        if tag.lstrip("#") in cfg.blocked_hashtags:
            add(BLOCK, "hashtag", "caption", f"{tag} is not allowed")
    return findings


def _engine_findings(post: Post, cfg: RulesConfig) -> list[Finding]:
    """Hook, CTA and pillar rules for posts made by the content engine."""
    out: list[Finding] = []
    hook = hook_text(post)
    if hook is not None:
        n = word_count(hook)
        if not (cfg.hook_min_words <= n <= cfg.hook_max_words):
            out.append(
                Finding(
                    BLOCK,
                    "hook",
                    "slide 1" if post.mode == Mode.render else "reel line 1",
                    f"hook has {n} words, need {cfg.hook_min_words}-{cfg.hook_max_words}: "
                    f"{hook[:60]!r}",
                )
            )
        lines = caption_lines(post.caption)
        if not lines or lines[0] != hook.strip():
            out.append(Finding(BLOCK, "hook", "caption line 1", "caption must open with the hook"))
    ctas = [line for line in caption_lines(post.caption) if line in set(cfg.cta)]
    if len(ctas) != 1:
        out.append(
            Finding(
                BLOCK,
                "cta",
                "caption",
                f"needs exactly one call to action from config/cta.yaml, found {len(ctas)}",
            )
        )
    if post.pillar is None:
        out.append(Finding(BLOCK, "pillar", "post", "pillar is missing"))
    return out


def pillar_rotation(posts: list[Post], cfg: RulesConfig) -> list[Finding]:
    """Two posts in a row (by publish time) may never share a pillar."""
    seq = sorted(
        (p for p in posts if is_engine_post(p, cfg) and p.pillar is not None),
        key=lambda p: (p.publish_at_dt, p.id),
    )
    return [
        Finding(BLOCK, "pillar", cur.id, f"same pillar {cur.pillar.value!r} as {prev.id}")
        for prev, cur in zip(seq, seq[1:], strict=False)
        if prev.pillar == cur.pillar
    ]


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


# Short connective lines ("תזכור:") may repeat; real quotes may not.
MIN_REPEAT_CHARS = 15


def quotes(post: Post, cta: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Normalized book quotes a post shows (slides, reel lines, caption hook).

    Call to action lines are not book quotes and may repeat across posts.
    """
    from .book import normalize

    out = []
    for _, text in post_texts(post):
        if text in cta:
            continue
        q = normalize(text)
        if len(q) >= MIN_REPEAT_CHARS and q not in out:
            out.append(q)
    return out


def repeated_quotes(posts: list[Post], cta: list[str] | tuple[str, ...] = ()) -> list[Finding]:
    """A quote may appear in one post only, so nothing from the book repeats.

    The caption hook repeats a line of its own post by design, so duplicates
    are counted per post, not per occurrence.
    """
    first: dict[str, str] = {}
    findings = []
    for post in sorted(posts, key=lambda p: (p.publish_at, p.id)):
        for q in quotes(post, cta):
            if q in first and first[q] != post.id:
                findings.append(
                    Finding(BLOCK, "repeat", post.id, f"already used in {first[q]}: {q[:50]!r}")
                )
            first.setdefault(q, post.id)
    return findings
