"""Job views and API request/response models for analyses (spec §8)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import (
    AnalysisStatus,
    JobKind,
    JobStatus,
    ResumeSource,
    Stage,
    WarningItem,
)
from app.schemas.roadmap import RoadmapWeek
from app.schemas.scoring import BreakdownRow, Gap
from app.schemas.skills import SkillMention

# ── Jobs ───────────────────────────────────────────────────────────────────


class JobView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    analysis_id: str
    kind: JobKind
    status: JobStatus
    stage: Stage | None = None
    progress: int
    attempts: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class JobCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    job_id: str
    status: JobStatus
    status_url: str
    analysis_url: str


# ── Analyses: requests ─────────────────────────────────────────────────────


class ResumePaste(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = "paste"
    text: str = Field(min_length=1)


class AnalysisCreate(BaseModel):
    """JSON create payload. Uploads use the multipart path instead."""

    model_config = ConfigDict(extra="forbid")

    resume: ResumePaste
    jd_text: str = Field(min_length=1)
    jd_title: str | None = Field(default=None, max_length=200)
    jd_company: str | None = Field(default=None, max_length=200)
    target_role: str | None = Field(default=None, max_length=200)
    roadmap_weeks: int = Field(default=6, ge=2, le=12)
    hours_per_week: int = Field(default=8, ge=1, le=40)
    force: bool = False


class RoadmapRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weeks: int | None = Field(default=None, ge=2, le=12)
    hours_per_week: int | None = Field(default=None, ge=1, le=40)
    force_regenerate: bool = False


# ── Analyses: responses ────────────────────────────────────────────────────


class InputsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_source: ResumeSource
    resume_filename: str | None = None
    resume_chars: int
    resume_truncated: bool
    jd_chars: int
    jd_truncated: bool


class CostView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0


class ScoreView(BaseModel):
    """The score block exactly as §8.8 returns it."""

    model_config = ConfigDict(extra="forbid")

    value: int
    band: str
    band_label: str
    coverage: float
    counts: dict
    breakdown: list[BreakdownRow]
    formula: str
    adjacent_credit: float


class GapView(Gap):
    aliases_checked: list[str] = Field(default_factory=list)


class RoadmapView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: str
    weeks: list[RoadmapWeek]


class ErrorView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: str
    status: AnalysisStatus
    role_label: str
    company: str | None = None
    match_score: int | None = None
    match_band: str | None = None
    gap_count: int = 0


class AnalysisList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AnalysisSummary]
    total: int
    limit: int
    offset: int


class AnalysisDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: str
    updated_at: str
    status: AnalysisStatus
    role_label: str
    company: str | None = None
    target_role: str | None = None
    roadmap_weeks: int
    hours_per_week: int
    inputs: InputsView
    score: dict | None = None
    gaps: list[GapView] = Field(default_factory=list)
    roadmap: RoadmapView | None = None
    resume_skills: list[SkillMention] = Field(default_factory=list)
    jd_skills: list[SkillMention] = Field(default_factory=list)
    cost: CostView = Field(default_factory=CostView)
    warnings: list[WarningItem] = Field(default_factory=list)
    error: ErrorView | None = None


class MetaView(BaseModel):
    version: str
    llm_enabled: bool
    limits: dict
    defaults: dict
    bands: list[dict]
