"""ASGI middleware: request IDs, security headers, body cap (§8.16, §10.2, §15.3).

Rate limiting lives in ``app.dependencies`` + the routes, because it keys on endpoint
and client address rather than on the raw request stream.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_setup import request_id_var

logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cache-Control": "no-store",
}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Outermost: every response echoes an ``X-Request-ID`` and logs carry it."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming[:64] if incoming else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.monotonic()
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            elapsed = (time.monotonic() - started) * 1000
            response.headers["Server-Timing"] = f"app;dur={elapsed:.0f}"
            logger.info(
                "%s %s -> %d in %.0fms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
            )
            return response
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        return response


class RateLimiter:
    """In-process sliding window keyed by client address (§8.14)."""

    def __init__(self, *, limit_per_hour: int, window_s: int = 3600) -> None:
        self.limit = limit_per_hour
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int, int]:
        """Return ``(allowed, remaining, retry_after_s)``."""
        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - self.window_s
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = int(self.window_s - (now - hits[0])) + 1
            return False, 0, retry_after
        hits.append(now)
        return True, self.limit - len(hits), 0

    def clear(self) -> None:
        self._hits.clear()


def _too_large_body(max_bytes: int) -> bytes:
    from app.errors import upload_too_large

    error = upload_too_large(max(1, max_bytes // (1024 * 1024)))
    payload = {
        "error": {
            "code": error.code,
            "message": error.message,
            "request_id": request_id_var.get() or "",
            "details": error.details,
        }
    }
    return json.dumps(payload).encode("utf-8")


class BodySizeLimitMiddleware:
    """Pure ASGI cap on the request body, enforced without buffering.

    The route's streaming reader enforces the same limit byte by byte; this exists so
    an oversized body is refused before any parsing work happens (§15.3 step 1).
    """

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in (scope.get("headers") or [])}
        declared = headers.get(b"content-length")
        if declared:
            try:
                if int(declared) > self.max_bytes:
                    await self._send_413(send)
                    return
            except ValueError:
                pass

        seen = 0
        rejected = False
        responded = False

        async def limited_receive():
            nonlocal seen, rejected
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    rejected = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            # Once the cap is hit, swallow the app's response and emit ours instead.
            nonlocal responded
            if rejected:
                if message["type"] == "http.response.body" and not responded:
                    responded = True
                    await self._send_413(send)
                return
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    async def _send_413(self, send) -> None:
        body = _too_large_body(self.max_bytes)
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def body_cap_for(settings) -> int:
    """Upload cap plus one mebibyte for multipart framing (§10.2 item 3)."""
    return settings.MAX_UPLOAD_MB * 1024 * 1024 + 1024 * 1024
