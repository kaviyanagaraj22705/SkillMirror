"""Stage orchestration: progress, partial results, per-stage error mapping (spec §10.4).

Reads as a linear script. Every database write is a short transaction that is closed
before the next ``await`` — a connection is never held across one (§9.2).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass

from app.config import Settings
from app.db.connection import connect, write_txn
from app.db.repositories import (
    analyses_repo,
    gaps_repo,
    jobs_repo,
    llm_repo,
    roadmap_repo,
    skills_repo,
)
from app.errors import AppError, jd_no_skills, no_gaps_to_roadmap
from app.llm.client import OpenRouterClient
from app.llm.dto import GapDTO
from app.schemas.common import AnalysisStatus, Side
from app.schemas.scoring import BreakdownRow, Gap
from app.schemas.skills import SkillMention
from app.services import extract as extract_service
from app.services import roadmap as roadmap_service
from app.services.normalization import SkillResolver, normalize_mentions
from app.services.scoring import build_gaps
from app.services.scoring import score as score_pair

logger = logging.getLogger(__name__)

UNKNOWN_ROLE = "this role"


@dataclass
class Warning:
    code: str
    message: str


class JobContext:
    """Everything a stage needs, plus the progress writer."""

    def __init__(
        self,
        *,
        settings: Settings,
        job_id: str,
        analysis_id: str,
        resolver: SkillResolver,
        client: OpenRouterClient | None,
    ) -> None:
        self.settings = settings
        self.job_id = job_id
        self.analysis_id = analysis_id
        self.resolver = resolver
        self.client = client
        self.warnings: list[Warning] = []

    @contextmanager
    def connection(self):
        """Short-lived connection, closed before the caller awaits anything else."""
        conn = connect(self.settings.DATABASE_PATH)
        try:
            yield conn
        finally:
            conn.close()

    def record_progress(self, stage: str | None, progress: int) -> None:
        with self.connection() as conn:
            with write_txn(conn):
                jobs_repo.update_progress(conn, self.job_id, stage=stage, progress=progress)

    def warn(self, code: str, message: str) -> None:
        self.warnings.append(Warning(code=code, message=message))


def _degraded_warning(ctx: JobContext, code: str) -> str:
    if code in ("LLM_AUTH_FAILED",):
        return (
            "Skill matching used keyword search only because OpenRouter rejected the API key. "
            "Check the key in your .env file."
        )
    if code == "LLM_DISABLED":
        return "Skill matching used keyword search only. Add an OpenRouter key for a full analysis."
    return (
        "Skill matching used keyword search only because the model did not respond in time. "
        "The score is still based on the skills found in your documents."
    )


def _persist_skills(ctx: JobContext, resume: list[SkillMention], jd: list[SkillMention]) -> None:
    with ctx.connection() as conn:
        with write_txn(conn):
            skills_repo.replace_side(conn, ctx.analysis_id, Side.RESUME, resume)
            skills_repo.replace_side(conn, ctx.analysis_id, Side.JD, jd)


def _persist_score(
    ctx: JobContext,
    *,
    score_value: int,
    band: str,
    breakdown: list,
    counts: dict,
    coverage: float,
    gaps: list[Gap],
) -> None:
    with ctx.connection() as conn:
        with write_txn(conn):
            analyses_repo.save_score(
                conn,
                ctx.analysis_id,
                value=score_value,
                band=band,
                breakdown={
                    "rows": [row.model_dump(mode="json") for row in breakdown],
                    "counts": counts,
                    "coverage": coverage,
                },
            )
            gaps_repo.replace(conn, ctx.analysis_id, gaps)


def _persist_roadmap(ctx: JobContext, weeks: list) -> None:
    with ctx.connection() as conn:
        with write_txn(conn):
            roadmap_repo.replace(conn, ctx.analysis_id, weeks)


def _finish(ctx: JobContext, status: AnalysisStatus, code: str | None = None) -> None:
    with ctx.connection() as conn:
        with write_txn(conn):
            analyses_repo.set_status(
                conn,
                ctx.analysis_id,
                status.value,
                error_code=code,
            )
            tokens_in, tokens_out, cost = llm_repo.usage_totals(conn, ctx.analysis_id)
            analyses_repo.save_usage(
                conn,
                ctx.analysis_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
            )


async def run_full_analysis(ctx: JobContext) -> None:
    record = None
    with ctx.connection() as conn:
        record = analyses_repo.get(conn, ctx.analysis_id)
    if record is None:
        raise AppError("ANALYSIS_NOT_FOUND", 404, "That analysis no longer exists.")

    with ctx.connection() as conn:
        with write_txn(conn):
            analyses_repo.set_status(conn, ctx.analysis_id, AnalysisStatus.RUNNING.value)

    ctx.record_progress("extract_resume", 10)
    resume_outcome, jd_outcome = await asyncio.gather(
        extract_service.extract_resume(
            record.resume_text,
            settings=ctx.settings,
            resolver=ctx.resolver,
            client=ctx.client,
            conn_factory=ctx.connection,
            analysis_id=ctx.analysis_id,
            job_id=ctx.job_id,
        ),
        extract_service.extract_jd(
            record.jd_text,
            settings=ctx.settings,
            resolver=ctx.resolver,
            client=ctx.client,
            conn_factory=ctx.connection,
            analysis_id=ctx.analysis_id,
            job_id=ctx.job_id,
        ),
    )
    ctx.record_progress("extract_jd", 50)

    degraded = resume_outcome.degraded or jd_outcome.degraded
    if degraded:
        code = resume_outcome.warning or jd_outcome.warning or "LLM_DISABLED"
        ctx.warn("DEGRADED_MODE", _degraded_warning(ctx, code))

    resume_skills = normalize_mentions(resume_outcome.mentions)
    jd_skills = normalize_mentions(jd_outcome.mentions)

    ctx.record_progress("score", 55)
    if not jd_skills:
        raise jd_no_skills()

    _persist_skills(ctx, resume_skills, jd_skills)

    result, adjacency = score_pair(
        jd_skills,
        resume_skills,
        adjacent_credit=ctx.settings.SCORING_ADJACENT_CREDIT,
        resolver=ctx.resolver,
    )
    gaps, _aliases = build_gaps(result.rows, adjacency=adjacency, resolver=ctx.resolver)

    if adjacency:
        ctx.warn(
            "PARTIAL_CREDIT_APPLIED",
            f"{len(adjacency)} skill(s) were credited as adjacent rather than direct matches.",
        )

    _persist_score(
        ctx,
        score_value=result.value,
        band=result.band.value,
        breakdown=result.rows,
        counts=result.counts.model_dump(),
        coverage=result.coverage,
        gaps=gaps,
    )
    ctx.record_progress("score", 70)

    if not ctx.settings.llm_available or ctx.client is None:
        ctx.record_progress(None, 95)
        _finish(ctx, AnalysisStatus.PARTIAL, "LLM_DISABLED")
        return

    if not gaps:
        ctx.record_progress(None, 95)
        _finish(ctx, AnalysisStatus.COMPLETED)
        return

    await _run_roadmap_stage(ctx, record, gaps, force=False)


async def _run_roadmap_stage(ctx: JobContext, record, gaps: list[Gap], *, force: bool) -> None:
    ctx.record_progress("generate_roadmap", 78)
    dto = GapDTO(
        target_role=record.target_role or record.jd_title or UNKNOWN_ROLE,
        seniority_hint=_seniority_hint(record.jd_text),
        weeks=record.roadmap_weeks,
        hours_per_week=record.hours_per_week,
        matched_skills=roadmap_service.matched_skill_bullets(_rows_for(record)),
        gaps=gaps,
    )
    try:
        clamped, _result = await roadmap_service.generate(
            dto,
            settings=ctx.settings,
            client=ctx.client,
            conn_factory=ctx.connection,
            analysis_id=ctx.analysis_id,
            job_id=ctx.job_id,
            force_regenerate=force,
        )
    except AppError as exc:
        logger.warning("Roadmap stage failed for %s: %s", ctx.analysis_id, exc.code)
        ctx.record_progress(None, 95)
        _finish(ctx, AnalysisStatus.PARTIAL, exc.code)
        return

    for message in clamped.warnings:
        ctx.warn("ROADMAP_CLAMPED", message)

    _persist_roadmap(ctx, clamped.weeks)
    ctx.record_progress(None, 98)
    _finish(ctx, AnalysisStatus.COMPLETED)


def _rows_for(record) -> list[BreakdownRow]:
    """Rebuild the breakdown rows from stored JSON for the DTO's matched-skills list."""
    stored = record.score_breakdown or {}
    return [BreakdownRow.model_validate(row) for row in stored.get("rows", [])]


def _seniority_hint(jd_text: str) -> str:
    lowered = jd_text.lower()
    for level in ("principal", "staff", "senior", "lead", "junior", "intern", "mid-level"):
        if level in lowered:
            return level
    return "not stated"


async def run_roadmap_only(ctx: JobContext) -> None:
    """Roadmap regeneration: extraction and scoring are not repeated (§8.10)."""
    with ctx.connection() as conn:
        record = analyses_repo.get(conn, ctx.analysis_id)
        gaps = gaps_repo.list_for(conn, ctx.analysis_id)
    if record is None:
        raise AppError("ANALYSIS_NOT_FOUND", 404, "That analysis no longer exists.")
    if not gaps:
        raise no_gaps_to_roadmap()

    with ctx.connection() as conn:
        with write_txn(conn):
            analyses_repo.set_status(conn, ctx.analysis_id, AnalysisStatus.RUNNING.value)

    await _run_roadmap_stage(ctx, record, gaps, force=True)
