"""Writes and reads for ``skill_gaps`` (spec §8.8, §9.3)."""

from __future__ import annotations

import sqlite3

from app.schemas.common import Importance, Priority, utc_now
from app.schemas.scoring import Gap


def replace(conn: sqlite3.Connection, analysis_id: str, gaps: list[Gap]) -> None:
    conn.execute("DELETE FROM skill_gaps WHERE analysis_id = ?", (analysis_id,))
    now = utc_now()
    conn.executemany(
        """
        INSERT INTO skill_gaps (
            analysis_id, canonical_name, display_name, category, priority, jd_importance,
            resume_strength, weight, impact, gap_reason, estimated_hours, sort_order, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                analysis_id,
                gap.canonical_name,
                gap.display_name,
                gap.category,
                gap.priority.value,
                gap.jd_importance.value,
                gap.resume_strength,
                gap.weight,
                gap.impact,
                gap.gap_reason,
                gap.estimated_hours,
                gap.sort_order,
                now,
            )
            for gap in gaps
        ],
    )


def list_for(conn: sqlite3.Connection, analysis_id: str) -> list[Gap]:
    rows = conn.execute(
        "SELECT canonical_name, display_name, category, priority, jd_importance, "
        "resume_strength, weight, impact, gap_reason, estimated_hours, sort_order "
        "FROM skill_gaps WHERE analysis_id = ? ORDER BY sort_order",
        (analysis_id,),
    ).fetchall()
    return [
        Gap(
            canonical_name=row["canonical_name"],
            display_name=row["display_name"],
            category=row["category"],
            priority=Priority(row["priority"]),
            jd_importance=Importance(row["jd_importance"]),
            resume_strength=row["resume_strength"],
            weight=row["weight"],
            impact=row["impact"],
            gap_reason=row["gap_reason"],
            estimated_hours=row["estimated_hours"],
            sort_order=row["sort_order"],
        )
        for row in rows
    ]


def count_for(conn: sqlite3.Connection, analysis_id: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM skill_gaps WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()[0]
    )
