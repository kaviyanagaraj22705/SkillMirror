"""Reads and writes for the ``analyses`` aggregate (spec §8.6–§8.9, §9.3)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.schemas.common import AnalysisStatus, utc_now


@dataclass(frozen=True)
class NewAnalysis:
    """Everything the create path persists, computed before the write transaction."""

    id: str
    resume_source: str
    resume_text: str
    resume_chars: int
    resume_truncated: bool
    jd_text: str
    jd_chars: int
    jd_truncated: bool
    prompt_version: str
    input_hash: str
    resume_filename: str | None = None
    resume_parse_meta: dict | None = None
    jd_title: str | None = None
    jd_company: str | None = None
    target_role: str | None = None
    roadmap_weeks: int = 6
    hours_per_week: int = 8
    model_extract: str | None = None
    model_roadmap: str | None = None
    status: str = AnalysisStatus.QUEUED.value


@dataclass
class AnalysisRecord:
    """A raw row, plus the two decoded JSON columns. Mutable on purpose."""

    id: str
    created_at: str
    updated_at: str
    status: str
    resume_source: str
    resume_text: str
    resume_chars: int
    resume_truncated: bool
    jd_text: str
    jd_chars: int
    jd_truncated: bool
    roadmap_weeks: int
    hours_per_week: int
    prompt_version: str
    input_hash: str
    resume_filename: str | None = None
    jd_title: str | None = None
    jd_company: str | None = None
    target_role: str | None = None
    resume_parse_meta: dict[str, Any] | None = None
    match_score: int | None = None
    match_band: str | None = None
    score_breakdown: dict[str, Any] | None = None
    model_extract: str | None = None
    model_roadmap: str | None = None
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    cost_usd: float = 0.0
    error_code: str | None = None
    error_message: str | None = None

    @property
    def role_label(self) -> str:
        """Fallback order is normative: target_role → jd_title → "Untitled analysis" (§8.7)."""
        return self.target_role or self.jd_title or "Untitled analysis"


def _decode(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def row_to_record(row: sqlite3.Row) -> AnalysisRecord:
    return AnalysisRecord(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status=row["status"],
        resume_source=row["resume_source"],
        resume_text=row["resume_text"],
        resume_chars=row["resume_chars"],
        resume_truncated=bool(row["resume_truncated"]),
        jd_text=row["jd_text"],
        jd_chars=row["jd_chars"],
        jd_truncated=bool(row["jd_truncated"]),
        roadmap_weeks=row["roadmap_weeks"],
        hours_per_week=row["hours_per_week"],
        prompt_version=row["prompt_version"],
        input_hash=row["input_hash"],
        resume_filename=row["resume_filename"],
        jd_title=row["jd_title"],
        jd_company=row["jd_company"],
        target_role=row["target_role"],
        resume_parse_meta=_decode(row["resume_parse_meta"]),
        match_score=row["match_score"],
        match_band=row["match_band"],
        score_breakdown=_decode(row["score_breakdown"]),
        model_extract=row["model_extract"],
        model_roadmap=row["model_roadmap"],
        total_tokens_in=row["total_tokens_in"],
        total_tokens_out=row["total_tokens_out"],
        cost_usd=row["cost_usd"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


_COLUMN_LIST = (
    "id",
    "created_at",
    "updated_at",
    "status",
    "resume_source",
    "resume_filename",
    "resume_text",
    "resume_chars",
    "resume_truncated",
    "resume_parse_meta",
    "jd_text",
    "jd_chars",
    "jd_truncated",
    "jd_title",
    "jd_company",
    "target_role",
    "roadmap_weeks",
    "hours_per_week",
    "match_score",
    "match_band",
    "score_breakdown",
    "model_extract",
    "model_roadmap",
    "prompt_version",
    "input_hash",
    "total_tokens_in",
    "total_tokens_out",
    "cost_usd",
    "error_code",
    "error_message",
)
_COLUMNS = ", ".join(_COLUMN_LIST)
_PLACEHOLDERS = ", ".join(["?"] * len(_COLUMN_LIST))


def insert(conn: sqlite3.Connection, new: NewAnalysis) -> str:
    """Insert one analysis row. Caller owns the transaction."""
    now = utc_now()
    conn.execute(
        f"INSERT INTO analyses ({_COLUMNS}) VALUES ({_PLACEHOLDERS})",
        (
            new.id,
            now,
            now,
            new.status,
            new.resume_source,
            new.resume_filename,
            new.resume_text,
            new.resume_chars,
            int(new.resume_truncated),
            json.dumps(new.resume_parse_meta) if new.resume_parse_meta else None,
            new.jd_text,
            new.jd_chars,
            int(new.jd_truncated),
            new.jd_title,
            new.jd_company,
            new.target_role,
            new.roadmap_weeks,
            new.hours_per_week,
            None,
            None,
            None,
            new.model_extract,
            new.model_roadmap,
            new.prompt_version,
            new.input_hash,
            0,
            0,
            0.0,
            None,
            None,
        ),
    )
    return new.id


def get(conn: sqlite3.Connection, analysis_id: str) -> AnalysisRecord | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    return row_to_record(row) if row else None


def find_recent_by_hash(
    conn: sqlite3.Connection, input_hash: str, *, since: str
) -> AnalysisRecord | None:
    """Duplicate guard (§8.6): an identical hash created since ``since``."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM analyses WHERE input_hash = ? AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 1",
        (input_hash, since),
    ).fetchone()
    return row_to_record(row) if row else None


def set_status(
    conn: sqlite3.Connection,
    analysis_id: str,
    status: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    conn.execute(
        "UPDATE analyses SET status = ?, error_code = ?, error_message = ?, updated_at = ? "
        "WHERE id = ?",
        (status, error_code, error_message, utc_now(), analysis_id),
    )


def save_score(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    value: int,
    band: str,
    breakdown: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE analyses SET match_score = ?, match_band = ?, score_breakdown = ?, "
        "updated_at = ? WHERE id = ?",
        (value, band, json.dumps(breakdown, sort_keys=True), utc_now(), analysis_id),
    )


def save_usage(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    conn.execute(
        "UPDATE analyses SET total_tokens_in = ?, total_tokens_out = ?, cost_usd = ?, "
        "updated_at = ? WHERE id = ?",
        (tokens_in, tokens_out, cost_usd, utc_now(), analysis_id),
    )


def save_roadmap_params(
    conn: sqlite3.Connection, analysis_id: str, *, weeks: int, hours_per_week: int
) -> None:
    conn.execute(
        "UPDATE analyses SET roadmap_weeks = ?, hours_per_week = ?, updated_at = ? WHERE id = ?",
        (weeks, hours_per_week, utc_now(), analysis_id),
    )


def list_page(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[AnalysisRecord], int]:
    where = "WHERE status = ?" if status else ""
    params: tuple[Any, ...] = (status,) if status else ()
    total = int(
        conn.execute(f"SELECT COUNT(*) FROM analyses {where}", params).fetchone()[0]
    )
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM analyses {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [row_to_record(r) for r in rows], total


def delete(conn: sqlite3.Connection, analysis_id: str) -> bool:
    cursor = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    return cursor.rowcount > 0


def gap_counts(conn: sqlite3.Connection, analysis_ids: list[str]) -> dict[str, int]:
    """One query for a page of summaries, instead of N (§8.7 needs ``gap_count``)."""
    if not analysis_ids:
        return {}
    placeholders = ", ".join(["?"] * len(analysis_ids))
    rows = conn.execute(
        f"SELECT analysis_id, COUNT(*) AS n FROM skill_gaps "
        f"WHERE analysis_id IN ({placeholders}) GROUP BY analysis_id",
        tuple(analysis_ids),
    ).fetchall()
    return {row["analysis_id"]: int(row["n"]) for row in rows}
