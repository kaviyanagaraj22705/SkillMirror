"""The LLM path, end to end, against a mocked transport (spec §16.2, §16.5).

``respx`` sits at the HTTP layer, so the real retry, structured-output and repair code
runs; only the vendor's bytes are faked.
"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

BASE = "https://openrouter.ai/api/v1"

RESUME_JSON = {
    "skills": [
        {
            "raw_label": "Python",
            "canonical_hint": "python",
            "category": "language",
            "proficiency": "advanced",
            "evidence": "Payments API (Python, FastAPI, PostgreSQL)",
        },
        {
            "raw_label": "FastAPI",
            "canonical_hint": "fastapi",
            "category": "framework",
            "proficiency": "advanced",
            "evidence": "Payments API (Python, FastAPI, PostgreSQL)",
        },
        {
            "raw_label": "PostgreSQL",
            "canonical_hint": "postgresql",
            "category": "database",
            "proficiency": "advanced",
            "evidence": "Payments API (Python, FastAPI, PostgreSQL)",
        },
        {
            "raw_label": "Docker",
            "canonical_hint": "docker",
            "category": "devops",
            "proficiency": "intermediate",
            "evidence": "Payments API (Python, FastAPI, PostgreSQL, Redis, Docker, AWS)",
        },
        {
            "raw_label": "AWS",
            "canonical_hint": "aws",
            "category": "cloud",
            "proficiency": "intermediate",
            "evidence": "Led migration of a monolith to services on AWS ECS",
        },
    ]
}

JD_JSON = {
    "title": "Senior Backend Engineer",
    "company": "Acme Payments",
    "seniority": "senior",
    "skills": [
        {"raw_label": "Python", "canonical_hint": "python", "category": "language",
         "importance": "required", "evidence": "5+ years Python"},
        {"raw_label": "FastAPI", "canonical_hint": "fastapi", "category": "framework",
         "importance": "required", "evidence": "strong FastAPI or Django"},
        {"raw_label": "PostgreSQL", "canonical_hint": "postgresql", "category": "database",
         "importance": "required", "evidence": "PostgreSQL and Redis"},
        {"raw_label": "Kubernetes", "canonical_hint": "kubernetes", "category": "devops",
         "importance": "required", "evidence": "Kubernetes in production"},
        {"raw_label": "Terraform", "canonical_hint": "terraform", "category": "devops",
         "importance": "required", "evidence": "Infrastructure as code with Terraform"},
        {"raw_label": "AWS", "canonical_hint": "aws", "category": "cloud",
         "importance": "required", "evidence": "AWS experience"},
        {"raw_label": "Kafka", "canonical_hint": "kafka", "category": "data",
         "importance": "preferred", "evidence": "Kafka for event streaming"},
    ],
}


def roadmap_json(weeks: int = 4) -> dict:
    return {
        "weeks": [
            {
                "week_number": index,
                "theme": f"Week {index} theme",
                "objective": f"Objective for week {index}.",
                "hours": 8,
                "focus_skills": ["kubernetes"],
                "items": [
                    {
                        "title": f"Task {index}",
                        "type": "read",
                        "details": "Read the official quickstart and take notes.",
                        "est_minutes": 90,
                        "resources": [
                            {"label": "Kubernetes docs", "url": "https://kubernetes.io/docs/",
                             "provider": "Kubernetes", "free": True}
                        ],
                    }
                ],
            }
            for index in range(1, weeks + 1)
        ]
    }


def _chat(content: dict | str, finish_reason: str = "stop") -> Response:
    body = content if isinstance(content, str) else json.dumps(content)
    return Response(
        200,
        json={
            "id": "gen-test",
            "model": "test/model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": body},
                 "finish_reason": finish_reason}
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 60,
                      "total_tokens": 160, "cost": 0.0003},
        },
    )


@respx.mock
@pytest.mark.asyncio
async def test_full_analysis_with_llm(llm_client, resume_text, jd_text):
    """Both extraction stages and the roadmap run through the mocked transport."""
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=lambda request: _route(request)
    )

    created = await llm_client.post(
        "/api/analyses/form",
        data={"resume_text": resume_text, "jd_text": jd_text, "roadmap_weeks": "4",
              "hours_per_week": "8"},
        headers={"X-SkillMirror-Client": "spa"},
    )
    assert created.status_code == 202
    body = created.json()

    job = await _wait_for_job(llm_client, body["job_id"])
    assert job["status"] == "succeeded", job
    assert job["progress"] == 100

    analysis = (await llm_client.get(body["analysis_url"])).json()
    assert analysis["status"] == "completed"
    assert analysis["score"]["value"] > 0
    assert analysis["score"]["band"] in {"strong", "competitive", "stretch", "foundational_gap"}
    assert len(analysis["roadmap"]["weeks"]) == 4
    assert [w["week_number"] for w in analysis["roadmap"]["weeks"]] == [1, 2, 3, 4]
    assert analysis["score"]["counts"]["missing"] >= 1
    gap_names = {gap["canonical_name"] for gap in analysis["gaps"]}
    assert "kubernetes" in gap_names


def _route(request) -> Response:
    payload = json.loads(request.content)
    system = payload["messages"][0]["content"]
    if "RESUME" in system:
        return _chat(RESUME_JSON)
    if "JOB DESCRIPTION" in system:
        return _chat(JD_JSON)
    return _chat(roadmap_json(weeks=payload.get("_weeks", 4)))


async def _wait_for_job(client, job_id: str, attempts: int = 60) -> dict:
    import asyncio

    last: dict = {}
    for _ in range(attempts):
        last = (await client.get(f"/api/jobs/{job_id}")).json()
        if last["status"] in {"succeeded", "failed", "interrupted"}:
            return last
        await asyncio.sleep(0.05)
    return last


@respx.mock
@pytest.mark.asyncio
async def test_extraction_retries_then_succeeds_on_429(llm_client, resume_text, jd_text):
    """A 429 is retried, not surfaced to the user (§12.4)."""
    calls: list[str] = []

    def route(request):
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        if "RESUME" in system:
            calls.append("resume")
            if len(calls) == 1:
                return Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})
            return _chat(RESUME_JSON)
        if "JOB DESCRIPTION" in system:
            return _chat(JD_JSON)
        return _chat(roadmap_json(4))

    respx.post(f"{BASE}/chat/completions").mock(side_effect=route)

    created = await llm_client.post(
        "/api/analyses/form",
        data={"resume_text": resume_text, "jd_text": jd_text, "roadmap_weeks": "4"},
        headers={"X-SkillMirror-Client": "spa"},
    )
    job = await _wait_for_job(llm_client, created.json()["job_id"])
    assert job["status"] == "succeeded"
    assert len(calls) >= 2


@respx.mock
@pytest.mark.asyncio
async def test_auth_failure_is_not_retried(llm_client, resume_text, jd_text):
    """401 fails fast: one attempt per stage, then keyword fallback (§12.4, §21.1).

    The job still succeeds - it degrades rather than erroring - but the analysis is
    ``partial`` with a visible LLM_AUTH_FAILED warning and the roadmap is absent.
    """
    calls: list[str] = []

    def route(request):
        calls.append(json.loads(request.content)["messages"][0]["content"][:24])
        return Response(401, json={"error": {"message": "bad key"}})

    respx.post(f"{BASE}/chat/completions").mock(side_effect=route)

    created = await llm_client.post(
        "/api/analyses/form",
        data={"resume_text": resume_text, "jd_text": jd_text},
        headers={"X-SkillMirror-Client": "spa"},
    )
    body = created.json()
    await _wait_for_job(llm_client, body["job_id"])

    # Three stages, one attempt each. A retry would show up as 4+ calls.
    assert len(calls) == 3, calls

    analysis = (await llm_client.get(body["analysis_url"])).json()
    assert analysis["status"] == "partial"
    assert analysis["roadmap"] is None
    codes = {warning["code"] for warning in analysis["warnings"]}
    assert "ROADMAP_FAILED" in codes
    # The deterministic half still produced a real score.
    assert analysis["score"] is not None
    assert analysis["score"]["value"] >= 0
