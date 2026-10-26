"""Regression tests for the bugs found while running the app by hand."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_delete_returns_a_bodyless_204(client, resume_text, jd_text):
    """A 204 must have no body: ``JSONResponse(content=None)`` wrote ``null`` (§8.10)."""
    created = await client.post(
        "/api/analyses/form",
        data={"resume_text": resume_text, "jd_text": jd_text, "roadmap_weeks": "3"},
        headers={"X-SkillMirror-Client": "spa"},
    )
    assert created.status_code == 202
    analysis_id = created.json()["analysis_id"]

    deleted = await client.delete(f"/api/analyses/{analysis_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""


@pytest.mark.asyncio
async def test_delete_missing_analysis_is_404(client):
    response = await client.delete("/api/analyses/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
