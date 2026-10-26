"""Reads and writes for ``jobs`` (spec §8.11, §9.3, §9.9)."""

from __future__ import annotations

import sqlite3

from app.schemas.analysis import JobView
from app.schemas.common import utc_now

_COLUMN_LIST = (
    "id",
    "analysis_id",
    "kind",
    "status",
    "stage",
    "progress",
    "attempts",
    "error_code",
    "error_message",
    "created_at",
    "started_at",
    "finished_at",
)
_COLUMNS = ", ".join(_COLUMN_LIST)
_PLACEHOLDERS = ", ".join(["?"] * len(_COLUMN_LIST))


def to_view(row: sqlite3.Row) -> JobView:
    return JobView(
        id=row["id"],
        analysis_id=row["analysis_id"],
        kind=row["kind"],
        status=row["status"],
        stage=row["stage"],
        progress=row["progress"],
        attempts=row["attempts"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def insert(
    conn: sqlite3.Connection, *, job_id: str, analysis_id: str, kind: str
) -> None:
    """Insert a queued job. Caller owns the transaction; commits before submit (§10.5)."""
    now = utc_now()
    conn.execute(
        f"INSERT INTO jobs ({_COLUMNS}) VALUES ({_PLACEHOLDERS})",
        (job_id, analysis_id, kind, "queued", None, 0, 0, None, None, now, None, None),
    )


def get(conn: sqlite3.Connection, job_id: str) -> JobView | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return to_view(row) if row else None


def active_for_analysis(conn: sqlite3.Connection, analysis_id: str) -> JobView | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM jobs WHERE analysis_id = ? "
        "AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
        (analysis_id,),
    ).fetchone()
    return to_view(row) if row else None


def mark_running(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = ?, "
        "heartbeat_at = ? WHERE id = ?",
        (utc_now(), utc_now(), job_id),
    )


def update_progress(
    conn: sqlite3.Connection, job_id: str, *, stage: str | None, progress: int
) -> None:
    """Progress is monotonic: a lower value is a no-op (§8.11)."""
    conn.execute(
        "UPDATE jobs SET stage = COALESCE(?, stage), progress = MAX(progress, ?), "
        "heartbeat_at = ? WHERE id = ?",
        (stage, progress, utc_now(), job_id),
    )


def mark_succeeded(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'succeeded', progress = 100, finished_at = ? WHERE id = ?",
        (utc_now(), job_id),
    )


def mark_failed(conn: sqlite3.Connection, job_id: str, code: str, message: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'failed', error_code = ?, error_message = ?, "
        "finished_at = ? WHERE id = ?",
        (code, message[:500], utc_now(), job_id),
    )


def mark_interrupted(conn: sqlite3.Connection, job_id: str, code: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'interrupted', error_code = ?, "
        "error_message = 'The run was cancelled.', finished_at = ? WHERE id = ?",
        (code, utc_now(), job_id),
    )
