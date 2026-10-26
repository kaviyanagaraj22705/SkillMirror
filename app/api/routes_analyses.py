"""Analysis endpoints: create, list, read, delete, roadmap retry (spec §8.6–§8.10)."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.config import Settings
from app.db.connection import write_txn
from app.db.repositories import (
    analyses_repo,
    gaps_repo,
    jobs_repo,
    llm_repo,
    roadmap_repo,
    skills_repo,
)
from app.dependencies import get_db, get_rate_limiter, get_runner, get_settings
from app.errors import (
    analysis_not_found,
    duplicate_analysis,
    job_already_running,
    llm_disabled,
    no_gaps_to_roadmap,
    upload_too_large,
)
from app.middleware import RateLimiter
from app.schemas.analysis import (
    AnalysisCreate,
    AnalysisDetail,
    AnalysisList,
    AnalysisSummary,
    CostView,
    GapView,
    InputsView,
    JobCreated,
    RoadmapRetryRequest,
    RoadmapView,
)
from app.schemas.common import AnalysisStatus, JobKind, Side
from app.schemas.scoring import BAND_LABELS, Band
from app.services import ingestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analyses", tags=["analyses"])

DUPLICATE_WINDOW_MINUTES = 10
UPLOAD_CHUNK = 64 * 1024


# ── helpers ───────────────────────────────────────────────────────────────


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_rate(limiter: RateLimiter, request: Request) -> None:
    from app.errors import rate_limited
    from app.middleware import RateLimiter as _R  # noqa: F401 - documented import site

    allowed, _remaining, retry_after = limiter.check(_client_key(request))
    if not allowed:
        raise rate_limited(limiter.limit, retry_after)


def _input_hash(*, resume_text: str, jd_text: str, weeks: int, hours: int, role: str | None) -> str:
    digest = hashlib.sha256()
    for part in (resume_text, jd_text, str(weeks), str(hours), role or ""):
        digest.update(part.encode("utf-8", errors="replace"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def _duplicate_since() -> str:
    return (
        (datetime.now(UTC) - timedelta(minutes=DUPLICATE_WINDOW_MINUTES))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


async def _read_upload(file) -> bytes:
    """Streaming read with a hard cap; never buffer the whole body first (§15.3.4)."""
    settings = get_settings()
    cap = settings.MAX_UPLOAD_MB * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise upload_too_large(settings.MAX_UPLOAD_MB, round(total / 1024 / 1024, 1))
        chunks.append(chunk)
    return b"".join(chunks)


def _job_payload(analysis_id: str, job_id: str) -> dict:
    return JobCreated(
        analysis_id=analysis_id,
        job_id=job_id,
        status="queued",
        status_url=f"/api/jobs/{job_id}",
        analysis_url=f"/api/analyses/{analysis_id}",
    ).model_dump()


def _create_rows(
    conn: sqlite3.Connection,
    *,
    new: analyses_repo.NewAnalysis,
    kind: str,
) -> str:
    """Insert analysis + job in one transaction; returns the job id."""
    from app.schemas.common import new_id

    job_id = new_id()
    analyses_repo.insert(conn, new)
    jobs_repo.insert(conn, job_id=job_id, analysis_id=new.id, kind=kind)
    return job_id


def _settings_model_names(settings: Settings) -> tuple[str | None, str | None]:
    if not settings.llm_available:
        return None, None
    return settings.OPENROUTER_MODEL_EXTRACT, settings.OPENROUTER_MODEL_ROADMAP


# ── create ────────────────────────────────────────────────────────────────


@router.post("", status_code=202)
async def create_analysis(
    payload: AnalysisCreate,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    runner=Depends(get_runner),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    _check_rate(limiter, request)

    ingested = ingestion.ingest_paste(payload.resume.text, settings)
    jd_text, jd_truncated, jd_chars = ingestion.clean_jd(payload.jd_text, settings)

    from app.schemas.common import new_id

    target_role = payload.target_role or payload.jd_title
    input_hash = _input_hash(
        resume_text=ingested.text,
        jd_text=jd_text,
        weeks=payload.roadmap_weeks,
        hours=payload.hours_per_week,
        role=target_role,
    )

    if not payload.force:
        existing = analyses_repo.find_recent_by_hash(conn, input_hash, since=_duplicate_since())
        if existing is not None:
            raise duplicate_analysis(existing.id)

    extract_model, roadmap_model = _settings_model_names(settings)
    from app.llm.prompts import PROMPT_VERSION_EXTRACT

    new = analyses_repo.NewAnalysis(
        id=new_id(),
        resume_source=ingested.source.value,
        resume_text=ingested.text,
        resume_chars=len(ingested.text),
        resume_truncated=ingested.truncated,
        resume_parse_meta=ingested.meta or None,
        jd_text=jd_text,
        jd_chars=jd_chars,
        jd_truncated=jd_truncated,
        jd_title=payload.jd_title,
        jd_company=payload.jd_company,
        target_role=payload.target_role,
        roadmap_weeks=payload.roadmap_weeks,
        hours_per_week=payload.hours_per_week,
        prompt_version=PROMPT_VERSION_EXTRACT,
        input_hash=input_hash,
        model_extract=extract_model,
        model_roadmap=roadmap_model,
    )

    with write_txn(conn):
        job_id = _create_rows(conn, new=new, kind=JobKind.FULL_ANALYSIS.value)

    runner.submit(job_id, new.id, JobKind.FULL_ANALYSIS.value)
    return JSONResponse(_job_payload(new.id, job_id), status_code=202)


@router.post("/form")
async def create_analysis_form(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    runner=Depends(get_runner),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """Multipart create. Answers JSON to the SPA, a 303 redirect to a plain form post (§7.9).

    The endpoint is shared so the browser and the no-JS path run identical validation;
    only the response shape differs, chosen by ``X-SkillMirror-Client``.
    """
    _check_rate(limiter, request)
    wants_json = request.headers.get("X-SkillMirror-Client") == "spa"
    form = await request.form()
    raw_resume = str(form.get("resume_text") or "")
    raw_jd = str(form.get("jd_text") or "")
    jd_title = str(form.get("jd_title") or "") or None
    jd_company = str(form.get("jd_company") or "") or None

    def _int(name: str, default: int) -> int:
        try:
            return int(str(form.get(name) or default))
        except ValueError:
            return default

    weeks = min(max(_int("roadmap_weeks", settings.ROADMAP_DEFAULT_WEEKS), 2), 12)
    hours = min(max(_int("hours_per_week", settings.ROADMAP_DEFAULT_HOURS_PER_WEEK), 1), 40)

    upload = form.get("file")
    if upload is not None and getattr(upload, "filename", ""):
        data = await _read_upload(upload)
        ingested = ingestion.ingest_file(data, upload.filename, settings)
    else:
        ingested = ingestion.ingest_paste(raw_resume, settings)

    jd_text, jd_truncated, jd_chars = ingestion.clean_jd(raw_jd, settings)

    from app.schemas.common import new_id

    target_role = jd_title
    input_hash = _input_hash(
        resume_text=ingested.text, jd_text=jd_text, weeks=weeks, hours=hours, role=target_role
    )
    existing = analyses_repo.find_recent_by_hash(conn, input_hash, since=_duplicate_since())
    if existing is not None:
        if wants_json:
            raise duplicate_analysis(existing.id)
        return RedirectResponse(f"/?analysis={existing.id}", status_code=303)

    extract_model, roadmap_model = _settings_model_names(settings)
    from app.llm.prompts import PROMPT_VERSION_EXTRACT

    new = analyses_repo.NewAnalysis(
        id=new_id(),
        resume_source=ingested.source.value,
        resume_text=ingested.text,
        resume_filename=ingested.filename,
        resume_chars=len(ingested.text),
        resume_truncated=ingested.truncated,
        resume_parse_meta=ingested.meta or None,
        jd_text=jd_text,
        jd_chars=jd_chars,
        jd_truncated=jd_truncated,
        jd_title=jd_title,
        jd_company=jd_company,
        target_role=target_role,
        roadmap_weeks=weeks,
        hours_per_week=hours,
        prompt_version=PROMPT_VERSION_EXTRACT,
        input_hash=input_hash,
        model_extract=extract_model,
        model_roadmap=roadmap_model,
    )
    with write_txn(conn):
        job_id = _create_rows(conn, new=new, kind=JobKind.FULL_ANALYSIS.value)

    runner.submit(job_id, new.id, JobKind.FULL_ANALYSIS.value)
    if wants_json:
        return JSONResponse(_job_payload(new.id, job_id), status_code=202)
    return RedirectResponse(f"/?analysis={new.id}", status_code=303)


# ── read ──────────────────────────────────────────────────────────────────


@router.get("")
def list_analyses(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
):
    records, total = analyses_repo.list_page(conn, limit=limit, offset=offset, status=status)
    counts = analyses_repo.gap_counts(conn, [record.id for record in records])
    items = [
        AnalysisSummary(
            id=record.id,
            created_at=record.created_at,
            status=record.status,
            role_label=record.role_label,
            company=record.jd_company,
            match_score=record.match_score,
            match_band=record.match_band,
            gap_count=counts.get(record.id, 0),
        ).model_dump()
        for record in records
    ]
    return AnalysisList(items=items, total=total, limit=limit, offset=offset).model_dump()


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str, conn: sqlite3.Connection = Depends(get_db)):
    record = analyses_repo.get(conn, analysis_id)
    if record is None:
        raise analysis_not_found(analysis_id)

    gaps = gaps_repo.list_for(conn, analysis_id)
    weeks = roadmap_repo.list_for(conn, analysis_id)
    generated = roadmap_repo.generated_at(conn, analysis_id)
    tokens_in, tokens_out, cost = llm_repo.usage_totals(conn, analysis_id)

    score_view = None
    if record.score_breakdown and record.match_score is not None:
        stored = record.score_breakdown
        band = Band(record.match_band)
        score_view = {
            "value": record.match_score,
            "band": record.match_band,
            "band_label": BAND_LABELS[band],
            "coverage": stored.get("coverage", 0.0),
            "counts": stored.get("counts", {}),
            "breakdown": stored.get("rows", []),
            "formula": "score = round(100 * Σ(weight × strength) / Σ(weight))",
            "adjacent_credit": get_settings().SCORING_ADJACENT_CREDIT,
        }

    detail = AnalysisDetail(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        status=record.status,
        role_label=record.role_label,
        company=record.jd_company,
        target_role=record.target_role,
        roadmap_weeks=record.roadmap_weeks,
        hours_per_week=record.hours_per_week,
        inputs=InputsView(
            resume_source=record.resume_source,
            resume_filename=record.resume_filename,
            resume_chars=record.resume_chars,
            resume_truncated=record.resume_truncated,
            jd_chars=record.jd_chars,
            jd_truncated=record.jd_truncated,
        ),
        score=score_view,
        gaps=[GapView(**gap.model_dump()) for gap in gaps],
        roadmap=(
            RoadmapView(generated_at=generated, weeks=weeks).model_dump()
            if weeks and generated
            else None
        ),
        resume_skills=[
            mention.model_dump() for mention in skills_repo.list_side(conn, analysis_id, Side.RESUME)
        ],
        jd_skills=[
            mention.model_dump() for mention in skills_repo.list_side(conn, analysis_id, Side.JD)
        ],
        cost=CostView(tokens_in=tokens_in, tokens_out=tokens_out, usd=round(cost, 6)),
        warnings=_warnings_for(record),
        error=(
            {"code": record.error_code, "message": record.error_message or ""}
            if record.error_code
            else None
        ),
    )
    return detail.model_dump()


def _warnings_for(record) -> list[dict]:
    warnings: list[dict] = []
    if record.status == AnalysisStatus.PARTIAL.value:
        if record.error_code == "LLM_DISABLED":
            warnings.append(
                {
                    "code": "DEGRADED_MODE",
                    "message": "Skill matching used keyword search only. Add an OpenRouter key "
                    "for a full analysis.",
                }
            )
        elif record.error_code and record.error_code.startswith("LLM_"):
            warnings.append(
                {
                    "code": "ROADMAP_FAILED",
                    "message": "We scored your fit, but couldn't build the roadmap.",
                }
            )
    if record.jd_truncated:
        warnings.append(
            {
                "code": "JD_TRUNCATED",
                "message": "That job description was long, so only the most relevant sections "
                "were analyzed.",
            }
        )
    if record.resume_truncated:
        warnings.append(
            {
                "code": "RESUME_TRUNCATED",
                "message": "That resume was long, so only the first part was analyzed.",
            }
        )
    return warnings


# ── delete ────────────────────────────────────────────────────────────────


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(
    analysis_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    record = analyses_repo.get(conn, analysis_id)
    if record is None:
        raise analysis_not_found(analysis_id)

    with write_txn(conn):
        llm_repo.detach_analysis(conn, analysis_id)
        analyses_repo.delete(conn, analysis_id)

    ingestion.remove_upload(record.resume_filename, settings)
    # 204 must carry no body at all: JSONResponse(content=None) would serialize the
    # four bytes "null" and uvicorn rejects a body on a 204.
    return Response(status_code=204)


# ── roadmap retry ─────────────────────────────────────────────────────────


@router.post("/{analysis_id}/roadmap", status_code=202)
async def retry_roadmap(
    analysis_id: str,
    payload: RoadmapRetryRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    runner=Depends(get_runner),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    _check_rate(limiter, request)

    record = analyses_repo.get(conn, analysis_id)
    if record is None:
        raise analysis_not_found(analysis_id)
    if not settings.llm_available:
        raise llm_disabled()

    active = jobs_repo.active_for_analysis(conn, analysis_id)
    if active is not None:
        raise job_already_running(analysis_id)

    gaps = gaps_repo.list_for(conn, analysis_id)
    if not gaps:
        raise no_gaps_to_roadmap()

    from app.schemas.common import new_id

    weeks = payload.weeks or record.roadmap_weeks
    hours = payload.hours_per_week or record.hours_per_week
    job_id = new_id()

    with write_txn(conn):
        analyses_repo.save_roadmap_params(conn, analysis_id, weeks=weeks, hours_per_week=hours)
        jobs_repo.insert(
            conn, job_id=job_id, analysis_id=analysis_id, kind=JobKind.ROADMAP_ONLY.value
        )
    runner.submit(job_id, analysis_id, JobKind.ROADMAP_ONLY.value)
    return JSONResponse(
        {
            "analysis_id": analysis_id,
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/jobs/{job_id}",
            "analysis_url": f"/api/analyses/{analysis_id}",
        },
        status_code=202,
    )
