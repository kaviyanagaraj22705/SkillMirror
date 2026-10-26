"""Matching the dictionary against raw document text (degraded mode and the alias pass)."""

from __future__ import annotations

import re

from app.schemas.common import ExtractionSource, Side
from app.schemas.skills import SkillMention
from app.services.normalization import SkillResolver, canonical_key

MAX_SCAN_CHARS = 40000


def _boundary_pattern(term: str) -> re.Pattern[str]:
    """Word-boundary regex that survives skill punctuation like C++, .NET, Node.js."""
    escaped = re.escape(term)
    # Lookarounds rather than \b: \b misbehaves next to '+' and '.'.
    return re.compile(rf"(?<![\w+#.]){escaped}(?![\w+#])", re.IGNORECASE)


def _context(text: str, start: int, end: int, window: int = 90) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    snippet = text[left:right].replace("\n", " ").strip()
    return re.sub(r"\s+", " ", snippet)


class DictionaryScanner:
    """Precompiled matcher over a resolver's vocabulary."""

    def __init__(self, resolver: SkillResolver) -> None:
        self.resolver = resolver
        patterns: dict[str, re.Pattern[str]] = {}
        # Longest terms first so "react native" wins over "react", "postgresql" over "sql".
        terms: set[str] = set()
        for entry in resolver.entries:
            terms.add(entry.canonical_name)
            terms.update(entry.aliases)
            terms.add(entry.display_name)
        for term in sorted(terms, key=len, reverse=True):
            key = canonical_key(term)
            if len(key) < 2:
                continue
            patterns.setdefault(key, _boundary_pattern(term))
        self._patterns = patterns
        self._terms = sorted(patterns, key=len, reverse=True)

    def scan(self, text: str, side: Side) -> list[SkillMention]:
        text = (text or "")[:MAX_SCAN_CHARS]
        if not text:
            return []

        # Find the longest match starting at each position; skip overlaps.
        taken: list[tuple[int, int]] = []
        hits: list[SkillMention] = []
        for term in self._terms:
            pattern = self._patterns[term]
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(s < end and start < e for s, e in taken):
                    continue
                found = self.resolver.resolve(term)
                if not found:
                    continue
                entry, source = found
                taken.append((start, end))
                hits.append(
                    SkillMention(
                        side=side,
                        raw_label=match.group(0)[:100],
                        canonical_name=entry.canonical_name,
                        display_name=entry.display_name,
                        category=entry.category,
                        evidence=_context(text, start, end),
                        confidence=0.6 if source is ExtractionSource.SEED else 0.55,
                        extraction_source=ExtractionSource.SEED,
                        verified=True,
                    )
                )
                if len(hits) >= 80:
                    return hits
        return hits
