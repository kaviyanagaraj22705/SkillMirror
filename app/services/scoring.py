"""Deterministic score, bands, and gap prioritization (spec §11.5–§11.6).

Nothing here calls a model. Same inputs always produce the same breakdown.
"""

from __future__ import annotations

from app.schemas.common import Band, Importance, MatchStatus, Priority, Side
from app.schemas.scoring import BreakdownRow, Counts, Gap, ScoreResult
from app.schemas.skills import SkillMention
from app.services.normalization import SkillResolver, canonical_key

WEIGHTS: dict[Importance, float] = {
    Importance.REQUIRED: 3.0,
    Importance.PREFERRED: 2.0,
    Importance.MENTIONED: 1.0,
}
STRENGTH_EXACT_WITH_EVIDENCE = 1.0
STRENGTH_EXACT_NAME_ONLY = 0.75
STRENGTH_ADJACENT = 0.25

BAND_CUTOFFS: tuple[tuple[Band, int], ...] = (
    (Band.STRONG, 80),
    (Band.COMPETITIVE, 65),
    (Band.STRETCH, 45),
    (Band.FOUNDATIONAL_GAP, 0),
)

PRIORITY_RANK: dict[Priority, int] = {
    Priority.CRITICAL: 1,
    Priority.HIGH: 2,
    Priority.MEDIUM: 3,
    Priority.LOW: 4,
}
ESTIMATED_HOURS: dict[Priority, int] = {
    Priority.CRITICAL: 16,
    Priority.HIGH: 10,
    Priority.MEDIUM: 6,
    Priority.LOW: 3,
}

FORMULA = "score = round(100 * Σ(weight × strength) / Σ(weight))"


def weight_for(importance: Importance | None) -> float:
    return WEIGHTS.get(importance or Importance.MENTIONED, 1.0)


def band_for(score: int) -> Band:
    for band, minimum in BAND_CUTOFFS:
        if score >= minimum:
            return band
    return Band.FOUNDATIONAL_GAP


def strength_for_mention(mention: SkillMention) -> float:
    """Resume-side strength for a single mention."""
    if mention.evidence:
        return STRENGTH_EXACT_WITH_EVIDENCE
    return STRENGTH_EXACT_NAME_ONLY


def compute_score(rows: list[BreakdownRow]) -> tuple[int, float, Band]:
    total_weight = sum(row.weight for row in rows)
    covered = sum(row.weight * row.strength for row in rows)
    coverage = covered / total_weight if total_weight else 0.0
    score = max(0, min(100, round(100 * coverage)))
    return score, round(coverage, 3), band_for(score)


def _status_for(strength: float) -> MatchStatus:
    if strength >= 1.0:
        return MatchStatus.MATCHED
    if strength > 0:
        return MatchStatus.PARTIAL
    return MatchStatus.MISSING


def _adjacent_source(
    gap_name: str, resume_names: set[str], resolver: SkillResolver | None
) -> str | None:
    """Return the resume skill that gives adjacent credit, if exactly one does."""
    if resolver is None:
        return None
    related = {canonical_key(r) for r in resolver.related_of(gap_name)}
    hits = sorted(related & resume_names)
    if not hits:
        return None
    # Reason strings read better with the dictionary's display name ("AWS", not "aws").
    entry = resolver.by_canonical.get(hits[0])
    return entry.display_name if entry else hits[0]



def build_breakdown(
    jd_skills: list[SkillMention],
    resume_skills: list[SkillMention],
    *,
    adjacent_credit: float = STRENGTH_ADJACENT,
    resolver: SkillResolver | None = None,
) -> tuple[list[BreakdownRow], dict[str, str]]:
    """One row per JD skill. Also returns ``{jd_skill: adjacent_source}`` for reasons."""
    resume_by_name: dict[str, SkillMention] = {}
    for mention in resume_skills:
        key = canonical_key(mention.canonical_name)
        existing = resume_by_name.get(key)
        if existing is None or strength_for_mention(mention) > strength_for_mention(existing):
            resume_by_name[key] = mention

    resume_names = set(resume_by_name)
    rows: list[BreakdownRow] = []
    adjacency: dict[str, str] = {}

    for jd in jd_skills:
        key = canonical_key(jd.canonical_name)
        source = resume_by_name.get(key)
        if source is not None:
            strength = strength_for_mention(source)
        else:
            adjacent = _adjacent_source(key, resume_names, resolver)
            if adjacent:
                strength = adjacent_credit
                adjacency[jd.canonical_name] = adjacent
            else:
                strength = 0.0

        weight = weight_for(jd.importance)
        rows.append(
            BreakdownRow(
                canonical_name=jd.canonical_name,
                display_name=jd.display_name,
                importance=jd.importance or Importance.MENTIONED,
                weight=weight,
                strength=strength,
                contribution=round(weight * strength, 4),
                status=_status_for(strength),
            )
        )

    # Stable, documented ordering: weight first, then name.
    rows.sort(key=lambda r: (-r.weight, r.canonical_name))
    return rows, adjacency


def score(
    jd_skills: list[SkillMention],
    resume_skills: list[SkillMention],
    *,
    adjacent_credit: float = STRENGTH_ADJACENT,
    resolver: SkillResolver | None = None,
) -> tuple[ScoreResult, dict[str, str]]:
    rows, adjacency = build_breakdown(
        jd_skills, resume_skills, adjacent_credit=adjacent_credit, resolver=resolver
    )
    value, coverage, band = compute_score(rows)
    counts = Counts(
        matched=sum(1 for r in rows if r.status is MatchStatus.MATCHED),
        partial=sum(1 for r in rows if r.status is MatchStatus.PARTIAL),
        missing=sum(1 for r in rows if r.status is MatchStatus.MISSING),
    )
    result = ScoreResult(value=value, band=band, coverage=coverage, rows=rows, counts=counts)
    return result, adjacency


def _priority_for(row: BreakdownRow, total_weight: float) -> tuple[Priority, float]:
    """Rules evaluated in the exact documented order (spec §11.6)."""
    strength = row.strength
    importance = row.importance
    weight_norm = row.weight / total_weight if total_weight else 0.0
    impact = round(weight_norm * (1 - strength), 4)

    if importance is Importance.REQUIRED and strength == 0:
        return Priority.CRITICAL, impact
    if importance is Importance.REQUIRED and strength < STRENGTH_EXACT_NAME_ONLY:
        return Priority.HIGH, impact
    if importance is Importance.PREFERRED and strength == 0:
        return Priority.HIGH, impact
    if impact >= 0.5:
        return Priority.HIGH, impact
    if impact >= 0.25:
        return Priority.MEDIUM, impact
    return Priority.LOW, impact


def _reason_for(
    row: BreakdownRow,
    priority: Priority,
    adjacent_source: str | None,
    aliases_checked: list[str],
) -> str:
    importance = row.importance
    if priority is Priority.CRITICAL:
        reason = "Required in the job description; not found on your resume."
    elif adjacent_source and importance is Importance.REQUIRED:
        reason = f"Required; adjacent to your {adjacent_source} experience (partial credit)."
    elif adjacent_source and importance is Importance.PREFERRED:
        reason = f"Preferred; adjacent to your {adjacent_source} experience (partial credit)."
    elif adjacent_source:
        reason = f"Mentioned in the job description; adjacent to your {adjacent_source} experience (partial credit)."
    elif importance is Importance.REQUIRED:
        reason = "Required; mentioned on your resume without supporting detail."
    elif importance is Importance.PREFERRED:
        reason = "Preferred in the job description; not found on your resume."
    else:
        reason = "Mentioned in the job description; not found on your resume."
    if aliases_checked:
        reason += f" (checked aliases: {', '.join(aliases_checked[:3])})"
    return reason


def build_gaps(
    rows: list[BreakdownRow],
    *,
    adjacency: dict[str, str] | None = None,
    resolver: SkillResolver | None = None,
) -> tuple[list[Gap], dict[str, list[str]]]:
    """Return prioritized gaps and the aliases that were checked for each."""
    adjacency = adjacency or {}
    total_weight = sum(row.weight for row in rows) or 1.0
    gap_rows = [row for row in rows if row.strength < 1.0]

    scored: list[tuple[Priority, float, BreakdownRow, str | None]] = []
    for row in gap_rows:
        priority, impact = _priority_for(row, total_weight)
        scored.append((priority, impact, row, adjacency.get(row.canonical_name)))

    scored.sort(
        key=lambda item: (
            PRIORITY_RANK[item[0]],
            -item[2].weight,
            item[2].canonical_name,
        )
    )

    gaps: list[Gap] = []
    aliases_used: dict[str, list[str]] = {}
    for index, (priority, impact, row, adjacent_source) in enumerate(scored, start=1):
        entry = resolver.by_canonical.get(canonical_key(row.canonical_name)) if resolver else None
        aliases = list(entry.aliases) if entry else []
        aliases_used[row.canonical_name] = aliases
        gaps.append(
            Gap(
                canonical_name=row.canonical_name,
                display_name=row.display_name,
                category=entry.category if entry else "other",
                priority=priority,
                jd_importance=row.importance,
                resume_strength=row.strength,
                weight=row.weight,
                impact=round(min(1.0, max(0.0, impact)), 4),
                gap_reason=_reason_for(row, priority, adjacent_source, aliases),
                estimated_hours=ESTIMATED_HOURS[priority],
                sort_order=index,
            )
        )
    return gaps, aliases_used


def jd_mentions(mentions: list[SkillMention]) -> list[SkillMention]:
    return [m for m in mentions if m.side is Side.JD]
