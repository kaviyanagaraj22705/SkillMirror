"""Exception handlers that produce the single error envelope (spec §8.3, §10.3)."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.errors import AppError
from app.logging_setup import request_id_var

logger = logging.getLogger(__name__)


def envelope(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_var.get() or "",
            "details": details,
        }
    }


_STATUS_CODES = {
    400: ("BAD_REQUEST", "That request could not be understood."),
    404: ("NOT_FOUND", "That page could not be found."),
    405: ("METHOD_NOT_ALLOWED", "That action isn't allowed here."),
}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        level = logging.WARNING if exc.http_status < 500 else logging.ERROR
        logger.log(level, "%s: %s", exc.code, exc.message)
        return JSONResponse(
            envelope(exc.code, exc.message, exc.details), status_code=exc.http_status
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            fields.append({"field": location or "request", "message": error.get("msg", "")})
        return JSONResponse(
            envelope("VALIDATION_ERROR", "Some fields need attention.", {"fields": fields}),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api") or request.url.path == "/healthz":
            code, message = _STATUS_CODES.get(
                exc.status_code, ("HTTP_ERROR", "That request could not be completed.")
            )
            return JSONResponse(envelope(code, message), status_code=exc.status_code)
        # HTML routes keep a human-readable 404.
        return Response(
            "<!doctype html><meta charset='utf-8'><title>Not found</title>"
            "<p style='font-family:system-ui;padding:2rem'>That page could not be found. "
            "<a href='/'>Back to SkillMirror</a></p>",
            status_code=exc.status_code,
            media_type="text/html",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            envelope(
                "INTERNAL_ERROR",
                "Something went wrong on our side. The details are below.",
            ),
            status_code=500,
        )
