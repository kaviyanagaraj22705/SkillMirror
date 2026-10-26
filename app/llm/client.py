"""OpenRouter transport: retries, structured output, repair, cache, call recording.

Contract lives in spec §12.2–§12.5. This module owns every HTTP detail; nothing above
it knows that OpenRouter exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import Settings, StructuredMode
from app.db.repositories import llm_repo
from app.errors import (
    AppError,
    llm_auth_failed,
    llm_model_unavailable,
    llm_rate_limited,
    llm_refused,
    llm_schema_invalid,
    llm_timeout,
    llm_truncated_output,
    llm_upstream_error,
)
from app.llm.dto import LLMRequest, LLMResult, Usage
from app.llm.validate import ParseAttempt, attempt_parse, build_repair_messages

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
NO_RETRY_STATUS = {400, 401, 403, 404, 422}
MAX_RETRY_AFTER_S = 30.0

# Models that rejected ``json_schema`` once, for the life of the process (§12.3).
_NO_STRICT_SCHEMA: set[str] = set()


def backoff_delay(attempt: int, retry_after: float | None) -> float:
    """1 s, 2 s, 4 s with ±20% jitter, or the provider's Retry-After (§12.4)."""
    if retry_after is not None:
        return min(retry_after, MAX_RETRY_AFTER_S)
    base = 2 ** (attempt - 1)
    return base * random.uniform(0.8, 1.2)


def cache_key(stage: str, model: str, prompt_version: str, canonical_input: str) -> str:
    digest = hashlib.sha256()
    digest.update(
        f"{stage}|{model}|{prompt_version}|".encode()
        + canonical_input.encode("utf-8", errors="replace")
    )
    return digest.hexdigest()


def request_hash(messages: list[dict[str, str]]) -> str:
    """Logged instead of prompt text when ``LOG_PROMPT_CONTENT`` is off (§10.6)."""
    blob = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class OpenRouterClient:
    """One instance per application lifespan, sharing a single ``AsyncClient``."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    # ── public API ────────────────────────────────────────────────────────

    async def complete(
        self,
        request: LLMRequest,
        model_cls: type[BaseModel],
        conn_factory,
    ) -> LLMResult:
        """Run one staged call. ``conn_factory`` yields a short-lived connection."""
        key = cache_key(
            request.stage.value, request.model, request.prompt_version, request.cache_input
        )
        if self._settings.LLM_CACHE_ENABLED and not request.force_regenerate:
            hit = self._read_cache(conn_factory, key)
            if hit is not None:
                attempt = attempt_parse(json.dumps(hit.payload), model_cls)
                if attempt.value is not None:
                    self._record(
                        conn_factory,
                        request,
                        Usage(hit.prompt_tokens, hit.completion_tokens, 0.0),
                        cache_hit=True,
                        model_resolved=request.model,
                    )
                    return LLMResult(
                        payload=hit.payload,
                        usage=Usage(hit.prompt_tokens, hit.completion_tokens, 0.0),
                        model_resolved=request.model,
                        cache_hit=True,
                    )
                logger.warning("Discarding an invalid cache entry for stage %s", request.stage)

        try:
            result = await asyncio.wait_for(
                self._run_with_retries(request, model_cls, conn_factory),
                timeout=request.timeout_s,
            )
        except TimeoutError as exc:
            raise llm_timeout(request.stage.value) from exc

        if self._settings.LLM_CACHE_ENABLED:
            self._write_cache(conn_factory, key, request, result)

        return result

    async def list_models(self) -> list[str]:
        """``GET /models`` for the startup slug check (§10.1 step 6). Never fatal."""
        try:
            response = await self._http.get(
                f"{self._settings.OPENROUTER_BASE_URL.rstrip('/')}/models",
                headers=self._headers(),
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - a catalog check must not block startup
            logger.warning("Could not fetch the OpenRouter model catalog: %s", exc.__class__.__name__)
            return []
        return [item.get("id", "") for item in payload.get("data", []) if item.get("id")]

    # ── internals ─────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        if self._settings.OPENROUTER_APP_URL:
            headers["HTTP-Referer"] = self._settings.OPENROUTER_APP_URL
        if self._settings.OPENROUTER_APP_NAME:
            headers["X-Title"] = self._settings.OPENROUTER_APP_NAME
        return headers

    def _body(self, request: LLMRequest, *, strict: bool, messages: list[dict[str, str]], temperature: float) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
            "usage": {"include": True},
        }
        if request.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
        provider: dict[str, Any] = {}
        if request.json_schema:
            provider["require_parameters"] = True
        if self._settings.OPENROUTER_DENY_DATA_COLLECTION:
            provider["data_collection"] = "deny"
        if provider:
            body["provider"] = provider
        return body

    def _structured_body(
        self,
        request: LLMRequest,
        messages: list[dict[str, str]],
        temperature: float,
        *,
        use_strict: bool,
    ) -> dict[str, Any]:
        body = self._body(
            request, strict=use_strict, messages=messages, temperature=temperature
        )
        if request.json_schema and not use_strict:
            body["response_format"] = {"type": "json_object"}
        return body

    def _strict_allowed(self, request: LLMRequest) -> bool:
        mode = self._settings.LLM_STRUCTURED_MODE
        return (
            bool(request.json_schema)
            and mode is not StructuredMode.JSON_OBJECT
            and request.model not in _NO_STRICT_SCHEMA
        )

    async def _run_with_retries(
        self, request: LLMRequest, model_cls: type[BaseModel], conn_factory
    ) -> LLMResult:
        attempts = self._settings.LLM_MAX_TRANSPORT_RETRIES
        last_error: AppError | None = None
        latency_total = 0
        schema_rejected = False

        for attempt in range(1, attempts + 1):
            use_strict = self._strict_allowed(request) and not schema_rejected
            started = time.monotonic()
            try:
                response = await self._http.post(
                    f"{self._settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
                    headers=self._headers(),
                    json=self._structured_body(
                        request, request.messages, request.temperature, use_strict=use_strict
                    ),
                )
            except httpx.TransportError as exc:
                last_error = llm_upstream_error(exc.__class__.__name__)
                logger.warning("Transport error on %s (attempt %d)", request.stage, attempt)
                if attempt < attempts:
                    await asyncio.sleep(backoff_delay(attempt, None))
                continue

            latency_total += int((time.monotonic() - started) * 1000)
            status = response.status_code

            if status in (401, 403):
                self._record(
                    conn_factory, request, Usage(),
                    http_status=status, retry_count=attempt - 1,
                    error_code="LLM_AUTH_FAILED",
                )
                raise llm_auth_failed()

            if status == 404:
                raise llm_model_unavailable(request.model)

            if status in RETRYABLE_STATUS:
                last_error = (
                    llm_rate_limited() if status == 429 else llm_upstream_error(f"HTTP {status}")
                )
                if attempt < attempts:
                    await asyncio.sleep(backoff_delay(attempt, _retry_after(response)))
                    continue
                self._record(
                    conn_factory, request, Usage(),
                    http_status=status, retry_count=attempt - 1,
                    error_code=last_error.code,
                )
                raise last_error

            if status >= 400:
                detail = response.text[:300]
                # A provider that rejects the strict schema is remembered for this
                # model and retried once with json_object (§12.3). Guarded by
                # ``schema_rejected`` so a second rejection cannot loop.
                if use_strict and _mentions_schema(detail):
                    _NO_STRICT_SCHEMA.add(request.model)
                    schema_rejected = True
                    logger.info("Model %s rejected json_schema; falling back", request.model)
                    continue
                self._record(
                    conn_factory, request, Usage(),
                    http_status=status, retry_count=attempt - 1,
                    error_code="LLM_UPSTREAM_ERROR", error_message=detail,
                )
                raise llm_upstream_error(detail)

            payload = self._safe_json(response)
            if payload is None:
                raise llm_schema_invalid("the response was not JSON")

            usage = self._usage(payload)
            model_resolved = payload.get("model") or request.model
            content, finish_reason = self._content(payload)

            if finish_reason in ("content_filter", "refusal"):
                self._record(conn_factory, request, usage, http_status=status, error_code="LLM_REFUSED")
                raise llm_refused()
            if finish_reason == "length":
                self._record(conn_factory, request, usage, http_status=status, error_code="LLM_TRUNCATED_OUTPUT")
                raise llm_truncated_output()

            parsed = await self._parse_or_repair(
                request, model_cls, content, usage, conn_factory, status,
                model_resolved, use_strict,
            )
            self._record(
                conn_factory, request, parsed.usage,
                http_status=status, model_resolved=model_resolved,
                retry_count=attempt - 1,
                repair_attempted=parsed.repair_attempted,
            )
            return LLMResult(
                payload=parsed.payload,
                usage=parsed.usage,
                model_resolved=model_resolved,
                repair_attempted=parsed.repair_attempted,
                retry_count=attempt - 1,
                latency_ms=latency_total,
            )

        raise last_error or llm_upstream_error("exhausted retries")

    async def _parse_or_repair(
        self,
        request: LLMRequest,
        model_cls: type[BaseModel],
        content: str,
        usage: Usage,
        conn_factory,
        status: int,
        model_resolved: str,
        use_strict: bool,
    ) -> _Parsed:
        attempt: ParseAttempt = attempt_parse(content, model_cls)
        if attempt.terminal is not None:
            self._record(
                conn_factory, request, usage,
                http_status=status, model_resolved=model_resolved,
                error_code=attempt.terminal.code,
            )
            raise attempt.terminal
        if attempt.value is not None:
            return _Parsed(
                payload=attempt.value.model_dump(mode="json"),
                usage=usage,
                repair_attempted=False,
            )

        # One repair round, temperature 0, no backoff (§12.3).
        repair_messages = build_repair_messages(request.messages, content, attempt.error)
        try:
            response = await self._http.post(
                f"{self._settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
                headers=self._headers(),
                json=self._structured_body(request, repair_messages, 0.0, use_strict=use_strict),
            )
        except httpx.TransportError as exc:
            raise llm_upstream_error(exc.__class__.__name__) from exc

        if response.status_code >= 400:
            self._record(
                conn_factory, request, usage,
                http_status=response.status_code, model_resolved=model_resolved,
                repair_attempted=True, error_code="LLM_SCHEMA_INVALID",
            )
            raise llm_schema_invalid(f"repair failed with HTTP {response.status_code}")

        repair_payload = self._safe_json(response) or {}
        repair_usage = self._add_usage(usage, self._usage(repair_payload))
        repair_content, repair_finish = self._content(repair_payload)

        if repair_finish == "length":
            raise llm_truncated_output()
        if repair_finish in ("content_filter", "refusal"):
            raise llm_refused()

        second: ParseAttempt = attempt_parse(repair_content, model_cls)
        if second.terminal is not None:
            raise second.terminal
        if second.value is None:
            self._record(
                conn_factory, request, repair_usage,
                http_status=status, model_resolved=model_resolved,
                repair_attempted=True, error_code="LLM_SCHEMA_INVALID",
                error_message=second.error,
            )
            raise llm_schema_invalid(second.error)

        return _Parsed(
            payload=second.value.model_dump(mode="json"),
            usage=repair_usage,
            repair_attempted=True,
        )

    # ── small helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _content(payload: dict[str, Any]) -> tuple[str, str]:
        choices = payload.get("choices") or []
        if not choices:
            return "", ""
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            # Some providers return content parts.
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return content, (choice.get("finish_reason") or "")

    @staticmethod
    def _usage(payload: dict[str, Any]) -> Usage:
        usage = payload.get("usage") or {}
        cost = usage.get("cost")
        if cost is None:
            # ``usage: {include: true}`` may return cost in a generation record; without
            # it we record zero rather than guess a price (§12.11).
            cost = 0.0
        return Usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cost_usd=float(cost or 0.0),
        )

    @staticmethod
    def _add_usage(a: Usage, b: Usage) -> Usage:
        return Usage(
            prompt_tokens=a.prompt_tokens + b.prompt_tokens,
            completion_tokens=a.completion_tokens + b.completion_tokens,
            cost_usd=round(a.cost_usd + b.cost_usd, 6),
        )

    def _record(
        self,
        conn_factory,
        request: LLMRequest,
        usage: Usage,
        *,
        model_resolved: str | None = None,
        http_status: int | None = None,
        retry_count: int = 0,
        repair_attempted: bool = False,
        cache_hit: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if conn_factory is None:
            return
        record = llm_repo.CallRecord(
            analysis_id=request.analysis_id,
            job_id=request.job_id,
            stage=request.stage.value,
            model_requested=request.model,
            model_resolved=model_resolved,
            prompt_version=request.prompt_version,
            request_hash=request_hash(request.messages),
            http_status=http_status,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
            retry_count=retry_count,
            repair_attempted=repair_attempted,
            cache_hit=cache_hit,
            error_code=error_code,
            error_message=error_message,
        )
        try:
            with conn_factory() as conn:
                llm_repo.record_call(conn, record)
        except Exception:  # noqa: BLE001 - observability must never break a call
            logger.warning("Could not record an llm_calls row", exc_info=True)

    def _read_cache(self, conn_factory, key: str):
        if conn_factory is None:
            return None
        try:
            with conn_factory() as conn:
                return llm_repo.get_cache(conn, key)
        except Exception:  # noqa: BLE001
            logger.warning("Cache read failed", exc_info=True)
            return None

    def _write_cache(self, conn_factory, key: str, request: LLMRequest, result: LLMResult) -> None:
        if conn_factory is None:
            return
        try:
            with conn_factory() as conn:
                llm_repo.put_cache(
                    conn,
                    cache_key=key,
                    stage=request.stage.value,
                    model=request.model,
                    prompt_version=request.prompt_version,
                    payload=result.payload,
                    prompt_tokens=result.usage.prompt_tokens,
                    completion_tokens=result.usage.completion_tokens,
                    ttl_days=self._settings.LLM_CACHE_TTL_DAYS,
                )
        except Exception:  # noqa: BLE001
            logger.warning("Cache write failed", exc_info=True)


def _mentions_schema(detail: str) -> bool:
    """True when a 4xx body blames the request's response_format (§12.3)."""
    lowered = detail.lower()
    return any(token in lowered for token in ("response_format", "json_schema", "schema"))


class _Parsed:
    __slots__ = ("payload", "usage", "repair_attempted")

    def __init__(self, payload: dict[str, Any], usage: Usage, repair_attempted: bool) -> None:
        self.payload = payload
        self.usage = usage
        self.repair_attempted = repair_attempted
