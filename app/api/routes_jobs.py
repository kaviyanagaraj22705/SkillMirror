"""``GET /api/jobs/{id}`` and ``POST /api/jobs/{id}/cancel`` (spec §8.11, §8.12)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.db.repositories import jobs_repo
from app.dependencies import get_db, get_runner
from app.errors import job_not_cancellable, job_not_found

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

TERMINAL = {"succeeded", "failed", "interrupted"}


@router.get("/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(get_db)):
    job = jobs_repo.get(conn, job_id)
    if job is None:
        raise job_not_found(job_id)
    return job.model_dump()


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    runner=Depends(get_runner),
):
    job = jobs_repo.get(conn, job_id)
    if job is None:
        raise job_not_found(job_id)
    if job.status in TERMINAL:
        raise job_not_cancellable()

    cancelled = await runner.cancel(job_id)
    if not cancelled:
        # The task may have finished between the read and the cancel.
        current = jobs_repo.get(conn, job_id)
        if current is None:
            raise job_not_found(job_id)
        if current.status in TERMINAL:
            raise job_not_cancellable()
    refreshed = jobs_repo.get(conn, job_id)
    return (refreshed or job).model_dump()
