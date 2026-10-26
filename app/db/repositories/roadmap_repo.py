"""Writes and reads for ``roadmap_weeks`` (spec §8.8, §9.3)."""

from __future__ import annotations

import json
import sqlite3

from app.schemas.common import utc_now
from app.schemas.roadmap import RoadmapWeek


def replace(conn: sqlite3.Connection, analysis_id: str, weeks: list[RoadmapWeek]) -> None:
    conn.execute("DELETE FROM roadmap_weeks WHERE analysis_id = ?", (analysis_id,))
    now = utc_now()
    conn.executemany(
        """
        INSERT INTO roadmap_weeks (
            analysis_id, week_number, theme, objective, hours, focus_skills, items, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                analysis_id,
                week.week_number,
                week.theme,
                week.objective,
                week.hours,
                json.dumps(week.focus_skills),
                json.dumps([item.model_dump(mode="json") for item in week.items]),
                now,
            )
            for week in weeks
        ],
    )


def list_for(conn: sqlite3.Connection, analysis_id: str) -> list[RoadmapWeek]:
    rows = conn.execute(
        "SELECT week_number, theme, objective, hours, focus_skills, items "
        "FROM roadmap_weeks WHERE analysis_id = ? ORDER BY week_number",
        (analysis_id,),
    ).fetchall()
    return [
        RoadmapWeek(
            week_number=row["week_number"],
            theme=row["theme"],
            objective=row["objective"],
            hours=row["hours"],
            focus_skills=json.loads(row["focus_skills"]),
            items=json.loads(row["items"]),
        )
        for row in rows
    ]


def generated_at(conn: sqlite3.Connection, analysis_id: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(created_at) FROM roadmap_weeks WHERE analysis_id = ?", (analysis_id,)
    ).fetchone()
    return row[0] if row and row[0] else None
