"""FastAPI dependencies: settings, DB connections, HTTP client, resolver (spec §10.4)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from fastapi import Request

from app.config import Settings
from app.config import get_settings as _get_settings
from app.db.connection import connect
from app.llm.client import OpenRouterClient
from app.services.normalization import SkillResolver


def get_settings() -> Settings:
    return _get_settings()


def get_db(request: Request) -> Iterator:
    """A connection per request, closed afterwards. Never held across an await."""
    conn = connect(request.app.state.settings.DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def get_conn_factory(request: Request):
    """Factory for the LLM layer, which writes in its own short transactions."""
    settings: Settings = request.app.state.settings

    @contextmanager
    def factory():
        conn = connect(settings.DATABASE_PATH)
        try:
            yield conn
        finally:
            conn.close()

    return factory


def get_http_client(request: Request) -> httpx.AsyncClient | None:
    return getattr(request.app.state, "http", None)


def get_llm_client(request: Request) -> OpenRouterClient | None:
    return getattr(request.app.state, "llm", None)


def get_resolver(request: Request) -> SkillResolver:
    return request.app.state.resolver


def get_runner(request: Request):
    return request.app.state.runner


def get_rate_limiter(request: Request):
    return request.app.state.rate_limiter
