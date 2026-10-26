"""Ping OpenRouter with the configured key and models (§12.2 smoke test).

    .venv\\Scripts\\python.exe scripts\\smoke_openrouter.py

Checks, in order:
  1. the key authenticates                  (GET /api/v1/key)
  2. each configured model is addressable   (GET /api/v1/models)
  3. a real structured roadmap call round-trips, including ``usage``

Exit code 0 = all good, 1 = something needs fixing. The probe sends a small synthetic
gap DTO - never your resume - and writes nothing to the database.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.config import get_settings
from app.db.connection import connector
from app.llm.client import OpenRouterClient
from app.llm.dto import GapDTO, LLMRequest
from app.llm.json_schemas import ROADMAP_SCHEMA
from app.llm.prompts import (
    PROMPT_VERSION_ROADMAP,
    ROADMAP_MAX_TOKENS,
    ROADMAP_TEMPERATURE,
    render_roadmap,
)
from app.schemas.common import Importance, Priority, Stage
from app.schemas.roadmap import LLMRoadmap
from app.schemas.scoring import Gap


def _probe_dto(weeks: int = 2, hours: int = 8) -> GapDTO:
    return GapDTO(
        target_role="Backend Engineer",
        seniority_hint="mid-level",
        weeks=weeks,
        hours_per_week=hours,
        matched_skills=[("Python", f"{1.0:.2f}")],
        gaps=[
            Gap(
                canonical_name="kubernetes",
                display_name="Kubernetes",
                category="devops",
                priority=Priority.CRITICAL,
                jd_importance=Importance.REQUIRED,
                resume_strength=0.0,
                weight=3.0,
                impact=0.6,
                gap_reason="Required in the job description; not found on your resume.",
                estimated_hours=16,
                sort_order=1,
            )
        ],
    )


async def main() -> int:
    settings = get_settings()
    if not settings.OPENROUTER_API_KEY:
        print("No OPENROUTER_API_KEY in .env - nothing to smoke test.")
        return 1

    base = settings.OPENROUTER_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}

    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=20.0) as http:
        key = await http.get("/key")
        if key.status_code != 200:
            print(f"[1/3] key check FAILED: {key.status_code} {key.text[:300]}")
            return 1
        body = key.json().get("data", {})
        print(f"[1/3] key OK  (label={body.get('label')!r}, limit={body.get('limit')})")

        models = await http.get("/models")
        available = {m["id"] for m in models.json().get("data", [])}
        wanted = [
            settings.OPENROUTER_MODEL_EXTRACT,
            settings.OPENROUTER_MODEL_ROADMAP,
            settings.OPENROUTER_MODEL_ROADMAP_FALLBACK,
        ]
        missing = [m for m in wanted if m and m not in available]
        if missing:
            print(f"[2/3] models MISSING from the catalogue: {missing}")
            print("      Pick a slug from https://openrouter.ai/models and update .env.")
            return 1
        print(f"[2/3] models OK  ({settings.OPENROUTER_MODEL_EXTRACT}, {settings.OPENROUTER_MODEL_ROADMAP})")

    system, user = render_roadmap(_probe_dto())
    request = LLMRequest(
        stage=Stage.GENERATE_ROADMAP,
        model=settings.OPENROUTER_MODEL_ROADMAP,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=ROADMAP_TEMPERATURE,
        max_tokens=ROADMAP_MAX_TOKENS,
        prompt_version=PROMPT_VERSION_ROADMAP,
        timeout_s=settings.LLM_TIMEOUT_ROADMAP_S,
        cache_input="smoke-test-probe",
        json_schema=ROADMAP_SCHEMA,
        schema_name="roadmap",
        force_regenerate=True,
    )

    conn_factory = connector(settings.DATABASE_PATH)
    timeout = httpx.Timeout(
        connect=10.0, read=float(settings.LLM_TIMEOUT_ROADMAP_S), write=30.0, pool=10.0
    )
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http:
        client = OpenRouterClient(settings, http)
        result = await client.complete(request, LLMRoadmap, conn_factory)

    weeks = len(result.payload.get("weeks", []))
    print(
        f"[3/3] roadmap OK  (model={result.model_resolved}, weeks={weeks}, "
        f"tokens={result.usage.prompt_tokens}+{result.usage.completion_tokens}, "
        f"cost=${result.usage.cost_usd:.6f})"
    )
    print("\nAll checks passed - the LLM path is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
