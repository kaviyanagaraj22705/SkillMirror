"""``GET /api/skills`` — dictionary search (spec §8.13)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from app.db.repositories import skills_repo
from app.dependencies import get_db

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/skills")
def search_skills(
    q: str = Query(min_length=2, max_length=60),
    limit: int = Query(default=10, ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"items": [item.model_dump() for item in skills_repo.search(conn, q, limit)]}
