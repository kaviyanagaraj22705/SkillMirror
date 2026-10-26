"""Shared enums, envelopes, and small value objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


def utc_now() -> str:
    """ISO-8601 UTC with milliseconds, e.g. ``2026-10-23T14:02:11.482Z`` (§8.1)."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    """UUID4 hex, 32 chars (§8.1)."""
    return uuid.uuid4().hex



class Side(StrEnum):
    RESUME = "resume"
    JD = "jd"


class Importance(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    MENTIONED = "mentioned"


class Proficiency(StrEnum):
    EXPERT = "expert"
    ADVANCED = "advanced"
    INTERMEDIATE = "intermediate"
    BASIC = "basic"
    UNKNOWN = "unknown"


class ExtractionSource(StrEnum):
    LLM = "llm"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    SEED = "seed"


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class JobKind(StrEnum):
    FULL_ANALYSIS = "full_analysis"
    ROADMAP_ONLY = "roadmap_only"


class Stage(StrEnum):
    EXTRACT_RESUME = "extract_resume"
    EXTRACT_JD = "extract_jd"
    SCORE = "score"
    GENERATE_ROADMAP = "generate_roadmap"


class Band(StrEnum):
    STRONG = "strong"
    COMPETITIVE = "competitive"
    STRETCH = "stretch"
    FOUNDATIONAL_GAP = "foundational_gap"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL = "partial"
    MISSING = "missing"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResumeSource(StrEnum):
    PASTE = "paste"
    PDF = "pdf"
    DOCX = "docx"


CATEGORIES = (
    "language",
    "framework",
    "database",
    "cloud",
    "devops",
    "data",
    "ml",
    "frontend",
    "backend",
    "mobile",
    "testing",
    "tool",
    "soft",
    "domain",
    "other",
)


@dataclass(frozen=True)
class CleanResult:
    """Output of ``services.text_clean``."""

    text: str
    original_chars: int
    final_chars: int
    truncated: bool
    pages: int | None = None
    removed_page_furniture: int = 0


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    details: dict | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class WarningItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
