"""In-process asyncio job runner with a concurrency semaphore (spec §10.4, §8.12)."""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.db.connection import connect, write_txn
from app.db.repositories import jobs_repo
from app.errors import AppError
from app.services import pipeline

logger = logging.getLogger(__name__)


class JobRunner:
    """One instance per process. Not restartable — A-3 (single process) makes it safe."""

    def __init__(self, *, settings: Settings, resolver, client) -> None:
        self._settings = settings
        self._resolver = resolver
        self._client = client
        self._sem = asyncio.Semaphore(settings.JOB_MAX_CONCURRENT)
        self._tasks: dict[str, asyncio.Task] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────

    def submit(self, job_id: str, analysis_id: str, kind: str) -> None:
        task = asyncio.create_task(self._run(job_id, analysis_id, kind))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── internals ─────────────────────────────────────────────────────────

    def _connection(self):
        return connect(self._settings.DATABASE_PATH)

    async def _run(self, job_id: str, analysis_id: str, kind: str) -> None:
        async with self._sem:
            with self._connection() as conn:
                with write_txn(conn):
                    jobs_repo.mark_running(conn, job_id)

            ctx = pipeline.JobContext(
                settings=self._settings,
                job_id=job_id,
                analysis_id=analysis_id,
                resolver=self._resolver,
                client=self._client,
            )
            try:
                if kind == "full_analysis":
                    await pipeline.run_full_analysis(ctx)
                else:
                    await pipeline.run_roadmap_only(ctx)
            except asyncio.CancelledError:
                self._mark(job_id, analysis_id, interrupted=True)
                raise
            except AppError as exc:
                logger.warning("Job %s failed: %s", job_id, exc.code)
                self._mark(job_id, analysis_id, code=exc.code, message=exc.message)
            except Exception:  # noqa: BLE001 - the runner is the last boundary
                logger.exception("Job %s crashed", job_id)
                self._mark(
                    job_id,
                    analysis_id,
                    code="INTERNAL_ERROR",
                    message="An unexpected error stopped this analysis.",
                )
            else:
                with self._connection() as conn:
                    with write_txn(conn):
                        jobs_repo.mark_succeeded(conn, job_id)

    def _mark(
        self,
        job_id: str,
        analysis_id: str,
        *,
        interrupted: bool = False,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        try:
            with self._connection() as conn:
                with write_txn(conn):
                    if interrupted:
                        jobs_repo.mark_interrupted(conn, job_id, "JOB_CANCELLED")
                        return
                    jobs_repo.mark_failed(conn, job_id, code or "INTERNAL_ERROR", message or "")
        except Exception:  # noqa: BLE001
            logger.exception("Could not record terminal state for job %s", job_id)

    @property
    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())
