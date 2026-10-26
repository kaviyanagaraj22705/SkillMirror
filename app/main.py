"""Application factory, lifespan, middleware wiring, and router registration (spec §10.1)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import exception_handlers
from app.api import routes_analyses, routes_health, routes_jobs, routes_pages, routes_skills
from app.config import Settings, get_settings
from app.db.connection import connect, write_txn
from app.db.migrate import upgrade
from app.db.repositories import llm_repo, skills_repo
from app.jobs import recovery
from app.jobs.runner import JobRunner
from app.llm.client import OpenRouterClient
from app.logging_setup import configure_logging
from app.middleware import (
    BodySizeLimitMiddleware,
    RateLimiter,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    body_cap_for,
)
from app.schemas.analysis import MetaView
from app.schemas.scoring import BAND_LABELS
from app.services import seed_skills
from app.services.normalization import SkillResolver
from app.services.scoring import BAND_CUTOFFS
from app.templating import TEMPLATES_DIR, build_templates

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _prepare_directories(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    if settings.KEEP_UPLOADS:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)


def bootstrap_database(settings: Settings) -> SkillResolver:
    """Migrate, seed, reconcile, then load the resolver — in that order (§10.1)."""
    upgrade(settings, quiet=True)

    conn = connect(settings.DATABASE_PATH)
    try:
        with write_txn(conn):
            seed_skills.load(conn)
        with write_txn(conn):
            llm_repo.purge_expired(conn)
        with write_txn(conn):
            recovery.reconcile(conn)
        entries = skills_repo.load_all(conn)
        seed_version = skills_repo.get_meta(conn, seed_skills.SEED_VERSION_KEY)
    finally:
        conn.close()

    logger.info(
        "Dictionary ready: %d skills (seed %s)", len(entries), seed_version or "unknown"
    )
    return SkillResolver(entries)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    _prepare_directories(settings)

    resolver = await asyncio.to_thread(bootstrap_database, settings)
    app.state.resolver = resolver

    timeout = httpx.Timeout(
        connect=10.0,
        read=float(settings.LLM_TIMEOUT_ROADMAP_S),
        write=30.0,
        pool=10.0,
    )
    http = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    app.state.http = http

    llm = OpenRouterClient(settings, http) if settings.llm_available else None
    app.state.llm = llm
    app.state.runner = JobRunner(settings=settings, resolver=resolver, client=llm)
    app.state.rate_limiter = RateLimiter(limit_per_hour=settings.MAX_ANALYSES_PER_HOUR)

    if not settings.llm_available:
        logger.warning(
            "No OpenRouter key configured: analyses run in degraded keyword mode."
        )
    elif llm is not None:
        asyncio.create_task(_check_model_catalog(llm, settings))

    try:
        yield
    finally:
        await app.state.runner.shutdown()
        await http.aclose()


async def _check_model_catalog(llm: OpenRouterClient, settings: Settings) -> None:
    """Warn (never fail) when a configured slug is missing from the catalog (§10.1)."""
    catalog = await llm.list_models()
    if not catalog:
        return
    for role, slug in (
        ("extract", settings.OPENROUTER_MODEL_EXTRACT),
        ("roadmap", settings.OPENROUTER_MODEL_ROADMAP),
    ):
        if slug and slug not in catalog:
            logger.warning(
                "Configured %s model %r is not in the OpenRouter catalog; "
                "analyses will fail on that stage until the slug is corrected.",
                role,
                slug,
            )


def meta_payload(settings: Settings) -> dict:
    bands = [
        {
            "name": band.value,
            "min_score": minimum,
            "label": BAND_LABELS[band],
        }
        for band, minimum in BAND_CUTOFFS
    ]
    return MetaView(
        version=settings.APP_VERSION,
        llm_enabled=settings.llm_available,
        limits={
            "max_upload_mb": settings.MAX_UPLOAD_MB,
            "max_resume_chars": settings.MAX_RESUME_CHARS,
            "max_jd_chars": settings.MAX_JD_CHARS,
            "min_text_chars": settings.MIN_TEXT_CHARS,
            "allowed_extensions": ["pdf", "docx"],
        },
        defaults={
            "roadmap_weeks": settings.ROADMAP_DEFAULT_WEEKS,
            "hours_per_week": settings.ROADMAP_DEFAULT_HOURS_PER_WEEK,
        },
        bands=bands,
    ).model_dump()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="SkillMirror",
        version=settings.APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.static_dir = STATIC_DIR
    app.state.templates_dir = TEMPLATES_DIR
    app.state.meta = meta_payload(settings)
    app.state.templates = build_templates(settings, app.state.meta)

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=body_cap_for(settings))
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)

    exception_handlers.install(app)

    app.include_router(routes_health.router)
    app.include_router(routes_pages.router)
    app.include_router(routes_analyses.router)
    app.include_router(routes_jobs.router)
    app.include_router(routes_skills.router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    if settings.APP_HOST not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "APP_HOST=%s is not a loopback address. SkillMirror has no authentication "
            "and will be reachable from your network.",
            settings.APP_HOST,
        )

    return app


app = create_app()
