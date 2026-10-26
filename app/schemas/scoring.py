"""Scoring, breakdown, and gap models (spec §8.8, Appendix B)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Band, Importance, MatchStatus, Priority


class BreakdownRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    display_name: str
    importance: Importance
    weight: float = Field(gt=0)
    strength: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0)
    status: MatchStatus


class Counts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: int = 0
    partial: int = 0
    missing: int = 0


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = Field(ge=0, le=100)
    band: Band
    coverage: float = Field(ge=0, le=1)
    rows: list[BreakdownRow]
    counts: Counts

    @property
    def band_label(self) -> str:
        return BAND_LABELS[self.band]


BAND_LABELS: dict[Band, str] = {
    Band.STRONG: "Strong match",
    Band.COMPETITIVE: "Competitive",
    Band.STRETCH: "Stretch",
    Band.FOUNDATIONAL_GAP: "Foundational gaps",
}


class Gap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    display_name: str
    category: str
    priority: Priority
    jd_importance: Importance
    resume_strength: float = Field(ge=0, le=1)
    weight: float = Field(gt=0)
    impact: float = Field(ge=0, le=1)
    gap_reason: str
    estimated_hours: int = Field(ge=1, le=200)
    sort_order: int = Field(ge=1)
