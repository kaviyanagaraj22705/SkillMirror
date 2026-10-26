"""Roadmap validation and clamping (spec §12.9 post-validation rules 1–7)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.config import Settings
from app.llm.client import OpenRouterClient
from app.llm.dto import GapDTO, LLMRequest
from app.llm.json_schemas import ROADMAP_SCHEMA
from app.llm.prompts import (
    PROMPT_VERSION_ROADMAP,
    ROADMAP_MAX_TOKENS,
    ROADMAP_TEMPERATURE,
    render_roadmap,
)
from app.schemas.common import Stage
from app.schemas.roadmap import ItemType, LLMRoadmap, Resource, RoadmapItem, RoadmapWeek

logger = logging.getLogger(__name__)

HOURS_TOLERANCE = 0.25
MIN_ITEMS_PER_WEEK = 1
MAX_ITEMS_PER_WEEK = 6


@dataclass
class ClampResult:
    weeks: list[RoadmapWeek] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def safe_resource_url(raw: str | None) -> str | None:
    """Only http(s) survives; anything else keeps the label and drops the URL (§12.9.5)."""
    if not raw:
        return None
    try:
        parsed = urlparse(raw.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    return raw.strip()[:500]


def _clamp_hours(hours: int, target: int, warnings: list[str], week_number: int) -> int:
    low = max(1, int(target * (1 - HOURS_TOLERANCE)))
    high = min(40, int(target * (1 + HOURS_TOLERANCE)) + 1)
    if low <= hours <= high:
        return hours
    clamped = min(max(hours, low), high)
    warnings.append(
        f"Week {week_number} was planned for {hours} hours; adjusted to {clamped} "
        f"to match your {target}-hour budget."
    )
    return clamped


def _clean_items(items: list[RoadmapItem]) -> list[RoadmapItem]:
    cleaned: list[RoadmapItem] = []
    for item in items:
        if not item.title.strip():
            continue
        resources: list[Resource] = []
        for resource in item.resources:
            url = safe_resource_url(resource.url)
            resources.append(resource.model_copy(update={"url": url}))
        cleaned.append(
            item.model_copy(
                update={
                    "title": item.title.strip()[:120],
                    "details": item.details.strip()[:400],
                    "resources": resources[:3],
                }
            )
        )
    return cleaned[:MAX_ITEMS_PER_WEEK]


def validate_and_clamp(raw: LLMRoadmap | dict, *, weeks: int, hours_per_week: int) -> ClampResult:
    """Rules 1–6 of §12.9. Never raises for model shape problems; records warnings."""
    model = raw if isinstance(raw, LLMRoadmap) else LLMRoadmap.model_validate(raw)
    result = ClampResult()

    ordered = sorted(model.weeks, key=lambda w: w.week_number)
    kept: list[RoadmapWeek] = []
    for position, week in enumerate(ordered, start=1):
        items = _clean_items(week.items)
        if len(items) < MIN_ITEMS_PER_WEEK:
            result.warnings.append(f"Week {position} had no usable tasks and was dropped.")
            continue
        kept.append(
            week.model_copy(
                update={
                    "week_number": position,  # rule 1: dense renumbering
                    "theme": week.theme.strip()[:80] or f"Week {position}",
                    "objective": week.objective.strip()[:300],
                    "hours": _clamp_hours(week.hours, hours_per_week, result.warnings, position),
                    "focus_skills": [s.strip()[:60] for s in week.focus_skills[:5] if s.strip()],
                    "items": items,
                }
            )
        )

    if not kept:
        return result

    if len(kept) != weeks:
        result.warnings.append(
            f"The plan came back with {len(kept)} weeks instead of {weeks}; "
            "showing what the model produced."
        )
        kept = kept[:weeks]
        # Renumber again after truncation so numbering stays 1..N (rule 4).
        kept = [week.model_copy(update={"week_number": i}) for i, week in enumerate(kept, 1)]

    result.weeks = kept
    return result


async def generate(
    dto: GapDTO,
    *,
    settings: Settings,
    client: OpenRouterClient,
    conn_factory,
    analysis_id: str | None = None,
    job_id: str | None = None,
    force_regenerate: bool = False,
) -> tuple[ClampResult, object]:
    """Run the roadmap stage and clamp the result. Raises ``AppError`` on upstream failure."""
    system, user = render_roadmap(dto)
    request = LLMRequest(
        stage=Stage.GENERATE_ROADMAP,
        model=settings.OPENROUTER_MODEL_ROADMAP,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=ROADMAP_TEMPERATURE,
        max_tokens=ROADMAP_MAX_TOKENS,
        prompt_version=PROMPT_VERSION_ROADMAP,
        timeout_s=settings.LLM_TIMEOUT_ROADMAP_S,
        cache_input=dto.canonical_input(),
        json_schema=ROADMAP_SCHEMA,
        schema_name="roadmap",
        analysis_id=analysis_id,
        job_id=job_id,
        force_regenerate=force_regenerate,
    )
    result = await client.complete(request, LLMRoadmap, conn_factory)
    clamped = validate_and_clamp(result.payload, weeks=dto.weeks, hours_per_week=dto.hours_per_week)
    return clamped, result


def matched_skill_bullets(rows) -> list[tuple[str, str]]:
    """Resume-side strengths the roadmap prompt may build on (§12.9 DTO rendering)."""
    bullets: list[tuple[str, str]] = []
    for row in rows:
        if row.strength >= 1.0:
            bullets.append((row.display_name, "strong"))
        elif row.strength > 0:
            bullets.append((row.display_name, "partial credit"))
    return sorted(bullets)


ITEM_TYPES = {item.value for item in ItemType}
