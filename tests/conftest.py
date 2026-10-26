"""Shared fixtures for the whole suite (spec §16.3).

Hermetic by default: no network, no real OpenRouter key, a fresh SQLite file per test.
LLM tests opt in explicitly and mock the transport with ``respx``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"

RESUME_TEXT = """Alex Rivera
Backend Engineer - 6 years

Experience
- Payments API (Python, FastAPI, PostgreSQL, Redis, Docker, AWS)
- Built CI pipelines with GitHub Actions; Terraform for infrastructure
- Led migration of a monolith to services on AWS ECS

Skills
Python, FastAPI, PostgreSQL, Redis, Docker, AWS, Terraform, Git, REST, SQL
"""

JD_TEXT = """Senior Backend Engineer at Acme Payments

We are hiring a Senior Backend Engineer to build payment infrastructure.

Requirements:
- 5+ years Python, strong FastAPI or Django
- PostgreSQL and Redis
- Kubernetes in production
- Infrastructure as code with Terraform
- AWS experience
- Kafka for event streaming

Responsibilities: design APIs, own reliability, mentor engineers.
"""


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_PATH=tmp_path / "test.db",
        UPLOAD_DIR=tmp_path / "uploads",
        OPENROUTER_API_KEY=None,
        LLM_ENABLED=False,
        LLM_CACHE_ENABLED=False,
        MAX_ANALYSES_PER_HOUR=100,
    )


@pytest.fixture
def llm_settings(settings) -> Settings:
    """Same as ``settings`` but with a fake key so the LLM path is enabled."""
    return settings.model_copy(update={"OPENROUTER_API_KEY": "test-key", "LLM_ENABLED": True})


@pytest.fixture
async def app(settings):
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def llm_app(llm_settings):
    application = create_app(llm_settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def llm_client(llm_app):
    transport = ASGITransport(app=llm_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def resolver(app):
    return app.state.resolver


@dataclass(frozen=True)
class Req:
    """A minimal stand-in for the request context services expect."""

    settings: Settings
    resolver: object
    client: object
    conn_factory: object
    analysis_id: str | None = None
    job_id: str | None = None


@pytest.fixture
def ctx(app, settings, resolver):
    from app.db.connection import connector

    return Req(
        settings=settings,
        resolver=resolver,
        client=None,
        conn_factory=connector(settings.DATABASE_PATH),
    )


# ── fixture helpers ───────────────────────────────────────────────────────


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def chat_payload(content: str, *, model: str = "test/model", finish_reason: str = "stop") -> dict:
    """Shape of an OpenRouter ``chat/completions`` response (§12.2)."""
    return {
        "id": "gen-test",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200, "cost": 0.0004},
    }


def chat_json(obj: dict, **kwargs) -> dict:
    return chat_payload(json.dumps(obj), **kwargs)


@pytest.fixture
def resume_text() -> str:
    return RESUME_TEXT


@pytest.fixture
def jd_text() -> str:
    return JD_TEXT
