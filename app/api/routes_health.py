"""``/healthz`` and ``/api/meta`` (spec §8.4, §8.5)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.db.migrate import current_version, discover
from app.dependencies import get_db, get_settings

router = APIRouter(tags=["meta"])


@router.get("/healthz")
def healthz(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    settings = get_settings()
    try:
        conn.execute("SELECT 1").fetchone()
        version = current_version(conn)
        pending = [name for v, path in discover() if v > version for name in [path.name]]
    except Exception:  # noqa: BLE001 - the probe reports, it does not crash
        return JSONResponse(
            {"status": "error", "db": "error", "llm_configured": settings.llm_available,
             "version": settings.APP_VERSION},
            status_code=503,
        )
    if pending:
        return JSONResponse(
            {"status": "degraded", "db": "ok", "llm_configured": settings.llm_available,
             "version": settings.APP_VERSION, "pending_migrations": pending},
            status_code=503,
        )
    return {
        "status": "ok",
        "db": "ok",
        "llm_configured": settings.llm_available,
        "version": settings.APP_VERSION,
    }


@router.get("/api/meta")
def meta(request: Request):
    return request.app.state.meta
