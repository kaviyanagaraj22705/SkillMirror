"""Skill resolution: dictionary first, fuzzy second, LLM labels last (spec §11.3–§11.4)."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process

from app.schemas.common import ExtractionSource, Importance, Proficiency, Side
from app.schemas.skills import DictionaryEntry, ResolvedSkill, SkillMention
from app.services.text_clean import sanitize_evidence

FUZZY_MIN_LEN = 5
FUZZY_THRESHOLD = 92
FUZZY_THRESHOLD_CROSS_CATEGORY = 97

# Hard blocklist: these are different skills that look alike (spec §11.4).
CONFUSABLE_PAIRS: set[frozenset[str]] = {
    frozenset({"java", "javascript"}),
    frozenset({"c", "c++"}),
    frozenset({"c", "c#"}),
    frozenset({"c++", "c#"}),
    frozenset({"sql", "mysql"}),
    frozenset({"sql", "postgresql"}),
    frozenset({"sql", "sqlite"}),
    frozenset({"mysql", "postgresql"}),
    frozenset({"react", "react native"}),
    frozenset({"node", "node.js"}),
    frozenset({".net", ".net core"}),
    frozenset({"ml", "machine learning"}),
    frozenset({"ai", "artificial intelligence"}),
    frozenset({"ux", "ui"}),
}

CONFIDENCE = {
    ExtractionSource.SEED: 0.98,
    ExtractionSource.ALIAS: 0.90,
    ExtractionSource.FUZZY: 0.75,
    ExtractionSource.LLM: 0.55,
}

_WS = re.compile(r"\s+")


def canonical_key(label: str) -> str:
    """NFKC → casefold → collapse whitespace. Punctuation is preserved.

    Only *trailing* sentence punctuation is dropped, so a label copied out of prose
    ("Python,") still matches. A leading dot is real for ".NET" and is kept (§11.3).
    """
    text = unicodedata.normalize("NFKC", label or "")
    text = text.casefold()
    text = _WS.sub(" ", text).strip()
    return text.rstrip(" .,;:")


def _lookup_form(key: str) -> str:
    """Secondary lookup form: drop diacritics and a simple trailing plural.

    Used only for matching, never stored — ``canonical_name`` keeps punctuation (§11.3).
    """
    base = "".join(ch for ch in unicodedata.normalize("NFD", key) if unicodedata.category(ch) != "Mn")
    words = base.split()
    if words:
        last = words[-1]
        if len(last) > 4 and last.endswith("s") and not last.endswith("ss"):
            words[-1] = last[:-1]
    return " ".join(words)


def is_confusable(a: str, b: str) -> bool:
    return frozenset({canonical_key(a), canonical_key(b)}) in CONFUSABLE_PAIRS


def _blocked(candidate: str, entry: DictionaryEntry) -> bool:
    """Refuse a fuzzy match if the two labels are a declared confusable pair."""
    return is_confusable(candidate, entry.canonical_name) or any(
        is_confusable(candidate, other)
        for other in (entry.display_name, *entry.aliases)
    )


class SkillResolver:
    """In-memory index over the ``skills`` table.

    Rebuilt on startup and after seeding; lookups are O(1) for exact/alias and a
    bounded scan for fuzzy.
    """

    def __init__(self, entries: list[DictionaryEntry]) -> None:
        self.entries = entries
        self.by_canonical: dict[str, DictionaryEntry] = {
            canonical_key(e.canonical_name): e for e in entries
        }
        self.by_alias: dict[str, DictionaryEntry] = {}
        for entry in entries:
            for alias in entry.aliases:
                self.by_alias.setdefault(canonical_key(alias), entry)
        # Lookup-form indexes (diacritics/plural tolerant).
        self.by_canonical_form = {_lookup_form(k): e for k, e in self.by_canonical.items()}
        self.by_alias_form = {_lookup_form(k): e for k, e in self.by_alias.items()}

        # Fuzzy candidates: every canonical name, display name and alias.
        self._choices: list[tuple[str, DictionaryEntry]] = []
        for entry in entries:
            names = {entry.canonical_name, entry.display_name, *entry.aliases}
            for name in names:
                self._choices.append((canonical_key(name), entry))

    # ── public API ────────────────────────────────────────────────────────

    def resolve(self, label: str) -> tuple[DictionaryEntry, ExtractionSource] | None:
        """Return the dictionary entry and how it matched, or ``None``."""
        key = canonical_key(label)
        if not key:
            return None

        if key in self.by_canonical:
            return self.by_canonical[key], ExtractionSource.SEED
        if key in self.by_alias:
            return self.by_alias[key], ExtractionSource.ALIAS

        form = _lookup_form(key)
        if form in self.by_canonical_form:
            return self.by_canonical_form[form], ExtractionSource.ALIAS
        if form in self.by_alias_form:
            return self.by_alias_form[form], ExtractionSource.ALIAS

        return self._fuzzy(key)

    def _fuzzy(self, key: str) -> tuple[DictionaryEntry, ExtractionSource] | None:
        if len(key) < FUZZY_MIN_LEN:
            # Short labels (C, R, Go, ML, AI) are far too collision-prone to fuzz.
            return None
        match = process.extractOne(
            key, [c for c, _ in self._choices], scorer=fuzz.token_set_ratio, score_cutoff=FUZZY_THRESHOLD
        )
        if not match:
            return None
        choice, score, _ = match
        entry = next(e for c, e in self._choices if c == choice)

        if _blocked(key, entry):
            return None
        # Different known categories need a near-exact match.
        if (
            entry.category != "other"
            and score < FUZZY_THRESHOLD_CROSS_CATEGORY
            and len(key.split()) != len(canonical_key(entry.canonical_name).split())
        ):
            return None
        return entry, ExtractionSource.FUZZY

    def to_resolved(self, entry: DictionaryEntry) -> ResolvedSkill:
        return ResolvedSkill(
            canonical_name=entry.canonical_name,
            display_name=entry.display_name,
            category=entry.category,
            aliases=list(entry.aliases),
            related=list(entry.related),
            confusables=list(entry.confusables),
        )

    def related_of(self, canonical_name: str) -> list[str]:
        entry = self.by_canonical.get(canonical_key(canonical_name))
        return list(entry.related) if entry else []

    def search(self, query: str, limit: int = 10) -> list[DictionaryEntry]:
        q = canonical_key(query)
        if len(q) < 2:
            return []
        hits: list[DictionaryEntry] = []
        seen: set[str] = set()
        for entry in self.entries:
            haystack = [entry.canonical_name, entry.display_name, *entry.aliases]
            if any(q in canonical_key(h) for h in haystack):
                if entry.canonical_name not in seen:
                    seen.add(entry.canonical_name)
                    hits.append(entry)
            if len(hits) >= limit:
                break
        return hits


def empty_resolver() -> SkillResolver:
    return SkillResolver([])


def resolve_mention(
    resolver: SkillResolver,
    *,
    side: Side,
    raw_label: str,
    canonical_hint: str | None = None,
    category: str = "other",
    importance: Importance | None = None,
    proficiency: Proficiency | None = None,
    evidence: str | None = None,
    hint_source: ExtractionSource = ExtractionSource.LLM,
) -> SkillMention | None:
    """Resolve one extracted mention to a canonical skill.

    An LLM ``canonical_hint`` is only a *search key* into the dictionary (spec §11.4);
    it never becomes a canonical name on its own. Unresolvable labels are kept as
    low-confidence LLM skills rather than dropped.
    """
    if not raw_label or not raw_label.strip():
        return None

    evidence = sanitize_evidence(evidence)

    for candidate in (canonical_hint, raw_label):
        if not candidate:
            continue
        found = resolver.resolve(candidate)
        if found:
            entry, source = found
            # A hint that resolved is still an LLM-sourced mention for provenance,
            # unless the raw label itself matched the dictionary exactly.
            raw_match = resolver.resolve(raw_label)
            if raw_match and raw_match[1] in (ExtractionSource.SEED, ExtractionSource.ALIAS):
                entry, source = raw_match
            confidence = CONFIDENCE[source]
            if source is ExtractionSource.FUZZY:
                confidence = 0.70
            return SkillMention(
                side=side,
                raw_label=raw_label.strip()[:100],
                canonical_name=entry.canonical_name,
                display_name=entry.display_name,
                category=entry.category,
                importance=importance if side is Side.JD else None,
                proficiency=proficiency if side is Side.RESUME else None,
                evidence=evidence,
                confidence=confidence,
                extraction_source=source,
                verified=bool(evidence),
            )

    # Unresolved: accept it, but flag it as model-asserted and unverified.
    key = canonical_key(raw_label)
    if not key:
        return None
    return SkillMention(
        side=side,
        raw_label=raw_label.strip()[:100],
        canonical_name=key,
        display_name=raw_label.strip()[:60],
        category=category if category else "other",
        importance=importance if side is Side.JD else None,
        proficiency=proficiency if side is Side.RESUME else None,
        evidence=evidence,
        confidence=CONFIDENCE[hint_source] * 0.6,
        extraction_source=hint_source,
        verified=False,
    )


_SOURCE_PRIORITY = {
    ExtractionSource.SEED: 4,
    ExtractionSource.ALIAS: 3,
    ExtractionSource.FUZZY: 2,
    ExtractionSource.LLM: 1,
}
_IMPORTANCE_RANK = {Importance.REQUIRED: 3, Importance.PREFERRED: 2, Importance.MENTIONED: 1}
_PROFICIENCY_RANK = {
    Proficiency.EXPERT: 5,
    Proficiency.ADVANCED: 4,
    Proficiency.INTERMEDIATE: 3,
    Proficiency.BASIC: 2,
    Proficiency.UNKNOWN: 1,
}


def merge_mentions(mentions: list[SkillMention]) -> list[SkillMention]:
    """Apply the documented merge policy (spec §9.4) in memory, preserving first order."""
    order: list[str] = []
    merged: dict[str, SkillMention] = {}

    for mention in mentions:
        key = mention.canonical_name
        if key not in merged:
            merged[key] = mention.model_copy()
            order.append(key)
            continue

        current = merged[key]
        if (
            mention.importance
            and _IMPORTANCE_RANK[mention.importance] > _IMPORTANCE_RANK.get(current.importance, 0)
        ):
            current.importance = mention.importance
        if (
            mention.proficiency
            and _PROFICIENCY_RANK[mention.proficiency]
            > _PROFICIENCY_RANK.get(current.proficiency, 0)
        ):
            current.proficiency = mention.proficiency
        if not current.evidence and mention.evidence:
            current.evidence = mention.evidence
        current.confidence = max(current.confidence, mention.confidence)
        if _SOURCE_PRIORITY[mention.extraction_source] > _SOURCE_PRIORITY[current.extraction_source]:
            current.extraction_source = mention.extraction_source
        current.verified = current.verified or mention.verified

    return [merged[key] for key in order]


def normalize_mentions(mentions: list[SkillMention]) -> list[SkillMention]:
    return merge_mentions(mentions)
