"""Startup reconciliation for jobs and analyses orphaned by a killed process (§9.9)."""

from __future__ import annotations

import logging
import sqlite3

from app.schemas.common import utc_now

logger = logging.getLogger(__name__)

RECONCILE_JOBS = """
UPDATE jobs
   SET status = 'interrupted',
       finished_at = ?,
       error_code = 'JOB_INTERRUPTED',
       error_message = 'The server stopped before this job finished.'
 WHERE status IN ('queued','running')
"""

RECONCILE_PARTIAL = """
UPDATE analyses
   SET status = 'partial',
       updated_at = ?
 WHERE status IN ('queued','running')
   AND match_score IS NOT NULL
"""

RECONCILE_FAILED = """
UPDATE analyses
   SET status = 'failed',
       error_code = 'JOB_INTERRUPTED',
       error_message = 'The server stopped before this analysis finished.',
       updated_at = ?
 WHERE status IN ('queued','running')
"""


def reconcile(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Return ``(jobs_interrupted, analyses_partial, analyses_failed)``.

    The caller owns the transaction so the three statements commit together.
    """
    now = utc_now()
    jobs = conn.execute(RECONCILE_JOBS, (now,)).rowcount
    partial = conn.execute(RECONCILE_PARTIAL, (now,)).rowcount
    failed = conn.execute(RECONCILE_FAILED, (now,)).rowcount
    if jobs or partial or failed:
        logger.warning(
            "Reconciled after an unclean stop: %d job(s), %d partial, %d failed",
            jobs,
            partial,
            failed,
        )
    return jobs, partial, failed
