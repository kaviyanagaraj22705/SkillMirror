"""Value objects exchanged with ``app.llm.client`` (spec §12.1–§12.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.common import Stage
from app.schemas.scoring import Gap


@dataclass(frozen=True)
class LLMStage:
    """Static per-stage configuration from the §12.1 stage table."""

    name: Stage
    temperature: float
    max_tokens: int
    prompt_version: str
    timeout_s: int
    require_strict_schema: bool = True


@dataclass(frozen=True)
class LLMRequest:
    stage: Stage
    model: str
    messages: list[dict[str, str]]
    temperature: float
    max_tokens: int
    prompt_version: str
    timeout_s: int
    cache_input: str
    """Canonical text hashed into the cache key (§12.5)."""
    json_schema: dict[str, Any] | None = None
    schema_name: str = "response"
    analysis_id: str | None = None
    job_id: str | None = None
    force_regenerate: bool = False


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class LLMResult:
    payload: dict[str, Any]
    usage: Usage
    model_resolved: str
    cache_hit: bool = False
    repair_attempted: bool = False
    retry_count: int = 0
    latency_ms: int = 0


@dataclass(frozen=True)
class GapDTO:
    """What the roadmap prompt is allowed to see (§12.9, D-02)."""

    target_role: str
    seniority_hint: str
    weeks: int
    hours_per_week: int
    matched_skills: list[tuple[str, str]] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)

    def canonical_input(self) -> str:
        """Stable serialization for the cache key: sorted, fixed precision (§12.5)."""
        matched = "\n".join(f"{name}|{strength}" for name, strength in sorted(self.matched_skills))
        gaps = "\n".join(
            "|".join(
                [
                    gap.display_name,
                    gap.priority.value,
                    gap.jd_importance.value,
                    f"{gap.resume_strength:.2f}",
                    str(gap.estimated_hours),
                    gap.gap_reason,
                ]
            )
            for gap in sorted(self.gaps, key=lambda g: (g.sort_order, g.canonical_name))
        )
        return (
            f"{self.target_role}\n{self.seniority_hint}\n{self.weeks}\n"
            f"{self.hours_per_week}\n{matched}\n{gaps}"
        )
