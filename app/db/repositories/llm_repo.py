"""Cache and call-recording for the LLM layer (spec §12.5, §12.11)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.schemas.common import utc_now


@dataclass(frozen=True)
class CacheHit:
    payload: dict
    prompt_tokens: int
    completion_tokens: int


def get_cache(conn: sqlite3.Connection, cache_key: str, *, now: str | None = None) -> CacheHit | None:
    """Expired rows are ignored (and left for the purge to collect)."""
    row = conn.execute(
        "SELECT response_json, prompt_tokens, completion_tokens, expires_at "
        "FROM llm_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if not row:
        return None
    current = now or utc_now()
    if row["expires_at"] and row["expires_at"] <= current:
        return None
    try:
        payload = json.loads(row["response_json"])
    except json.JSONDecodeError:
        return None
    conn.execute(
        "UPDATE llm_cache SET hit_count = hit_count + 1 WHERE cache_key = ?", (cache_key,)
    )
    return CacheHit(
        payload=payload,
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
    )


def put_cache(
    conn: sqlite3.Connection,
    *,
    cache_key: str,
    stage: str,
    model: str,
    prompt_version: str,
    payload: dict,
    prompt_tokens: int,
    completion_tokens: int,
    ttl_days: int,
) -> None:
    """Failures are never cached; only validated payloads reach here (§12.5)."""
    expires = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO llm_cache (
            cache_key, stage, model, prompt_version, response_json,
            prompt_tokens, completion_tokens, hit_count, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT (cache_key) DO UPDATE SET
            response_json = excluded.response_json,
            prompt_tokens = excluded.prompt_tokens,
            completion_tokens = excluded.completion_tokens,
            created_at = excluded.created_at,
            expires_at = excluded.expires_at
        """,
        (
            cache_key,
            stage,
            model,
            prompt_version,
            json.dumps(payload, sort_keys=True),
            prompt_tokens,
            completion_tokens,
            utc_now(),
            expires,
        ),
    )


def purge_expired(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    cursor = conn.execute(
        "DELETE FROM llm_cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
        (now or utc_now(),),
    )
    return cursor.rowcount


@dataclass(frozen=True)
class CallRecord:
    analysis_id: str | None
    job_id: str | None
    stage: str
    model_requested: str
    prompt_version: str
    request_hash: str
    model_resolved: str | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float = 0.0
    retry_count: int = 0
    repair_attempted: bool = False
    cache_hit: bool = False
    error_code: str | None = None
    error_message: str | None = None


def record_call(conn: sqlite3.Connection, call: CallRecord) -> None:
    conn.execute(
        """
        INSERT INTO llm_calls (
            analysis_id, job_id, stage, model_requested, model_resolved, prompt_version,
            request_hash, http_status, latency_ms, prompt_tokens, completion_tokens,
            cost_usd, retry_count, repair_attempted, cache_hit, error_code, error_message,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            call.analysis_id,
            call.job_id,
            call.stage,
            call.model_requested,
            call.model_resolved,
            call.prompt_version,
            call.request_hash,
            call.http_status,
            call.latency_ms,
            call.prompt_tokens,
            call.completion_tokens,
            call.cost_usd,
            call.retry_count,
            int(call.repair_attempted),
            int(call.cache_hit),
            call.error_code,
            (call.error_message or "")[:300] or None,
            utc_now(),
        ),
    )


def usage_totals(conn: sqlite3.Connection, analysis_id: str) -> tuple[int, int, float]:
    row = conn.execute(
        "SELECT COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0), "
        "COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE analysis_id = ?",
        (analysis_id,),
    ).fetchone()
    return int(row[0]), int(row[1]), float(row[2])


def detach_analysis(conn: sqlite3.Connection, analysis_id: str) -> None:
    """§8.9: llm_calls rows outlive the analysis, with ``analysis_id`` nulled."""
    conn.execute("UPDATE llm_calls SET analysis_id = NULL WHERE analysis_id = ?", (analysis_id,))
