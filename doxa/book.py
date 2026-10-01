"""The book text, used to prove every post is quoted word for word.

The book is never committed to this public repo. Workflows check out the
private repo ``silverfox-il/doxa-private`` into ``private/``; locally it may
also sit in ``_incoming/book``. ``DOXA_BOOK_DIR`` overrides both.

Only clean sources count: ``*.md`` (new edition) and ``old_clean/*.md``
(old-edition passages cleaned by hand). The raw ``old/*.txt`` PDF extracts have
broken line order, so they can never prove a quote.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse all whitespace (line breaks we add for layout don't matter)."""
    return _WS.sub(" ", text).strip()


def find_book_dir(root: Path) -> Path | None:
    env = os.environ.get("DOXA_BOOK_DIR")
    candidates = [Path(env)] if env else []
    candidates += [root / "private" / "book", root / "_incoming" / "book"]
    for c in candidates:
        if c.is_dir() and any(c.glob("*.md")):
            return c
    return None


@dataclass
class Book:
    text: str  # normalized full text of all clean sources

    @classmethod
    def load(cls, book_dir: Path) -> Book:
        files = sorted(book_dir.glob("*.md")) + sorted((book_dir / "old_clean").glob("*.md"))
        return cls(normalize("\n".join(f.read_text(encoding="utf-8") for f in files)))

    @classmethod
    def find(cls, root: Path) -> Book | None:
        d = find_book_dir(root)
        return cls.load(d) if d else None

    def contains(self, quote: str) -> bool:
        q = normalize(quote)
        return bool(q) and q in self.text
