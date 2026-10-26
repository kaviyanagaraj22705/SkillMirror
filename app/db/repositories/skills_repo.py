"""The ``skills`` dictionary and the per-analysis ``analysis_skills`` rows.

Covers spec §9.7 (seeding), §8.13 (search), and §9.4 (merge policy).
"""

from __future__ import annotations

import json
import sqlite3

from app.schemas.common import Importance, Proficiency, Side, utc_now
from app.schemas.skills import DictionaryEntry, SkillMention, SkillSearchItem

# ── Reference dictionary ──────────────────────────────────────────────────


def load_all(conn: sqlite3.Connection) -> list[DictionaryEntry]:
    rows = conn.execute(
        "SELECT canonical_name, display_name, category, aliases_json, related_json, "
        "confusables_json FROM skills ORDER BY canonical_name"
    ).fetchall()
    return [
        DictionaryEntry(
            canonical_name=row["canonical_name"],
            display_name=row["display_name"],
            category=row["category"],
            aliases=json.loads(row["aliases_json"]),
            related=json.loads(row["related_json"]),
            confusables=json.loads(row["confusables_json"]),
        )
        for row in rows
    ]


def count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0])


def upsert_many(conn: sqlite3.Connection, entries: list[DictionaryEntry]) -> int:
    """Idempotent load; user-added rows (``is_seeded = 0``) are never touched (§9.7)."""
    now = utc_now()
    for entry in entries:
        conn.execute(
            """
            INSERT INTO skills (
                canonical_name, display_name, category, aliases_json, related_json,
                confusables_json, is_seeded, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT (canonical_name) DO UPDATE SET
                display_name = excluded.display_name,
                category = excluded.category,
                aliases_json = excluded.aliases_json,
                related_json = excluded.related_json,
                confusables_json = excluded.confusables_json
            WHERE skills.is_seeded = 1
            """,
            (
                entry.canonical_name,
                entry.display_name,
                entry.category,
                json.dumps(entry.aliases),
                json.dumps(entry.related),
                json.dumps(entry.confusables),
                now,
            ),
        )
    return len(entries)


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _escape_like(term: str) -> str:
    """§15.4: ``%``, ``_`` and ``\\`` in a user term must be literals, not wildcards."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[SkillSearchItem]:
    """Substring search over canonical name, display name, and the alias JSON (§8.13)."""
    like = f"%{_escape_like(query)}%"
    rows = conn.execute(
        """
        SELECT canonical_name, display_name, category, aliases_json
          FROM skills
         WHERE canonical_name LIKE ? ESCAPE '\\' COLLATE NOCASE
            OR display_name LIKE ? ESCAPE '\\' COLLATE NOCASE
            OR aliases_json LIKE ? ESCAPE '\\' COLLATE NOCASE
         ORDER BY LENGTH(canonical_name), canonical_name
         LIMIT ?
        """,
        (like, like, like, limit),
    ).fetchall()
    return [
        SkillSearchItem(
            canonical_name=row["canonical_name"],
            display_name=row["display_name"],
            category=row["category"],
            aliases=json.loads(row["aliases_json"]),
        )
        for row in rows
    ]


# ── Per-analysis mentions ─────────────────────────────────────────────────

# Merge policy (§9.4): max importance, max proficiency, first non-empty evidence,
# max confidence, and extraction_source by source priority — implemented in SQL so
# the database stays the single source of truth.
_UPSERT = """
INSERT INTO analysis_skills (
    analysis_id, side, raw_label, canonical_name, display_name, category,
    importance, proficiency, evidence, confidence, extraction_source, verified, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (analysis_id, side, canonical_name) DO UPDATE SET
    importance = CASE
        WHEN excluded.importance IS NULL THEN importance
        WHEN importance IS NULL THEN excluded.importance
        WHEN CASE excluded.importance WHEN 'required' THEN 3 WHEN 'preferred' THEN 2 ELSE 1 END
           > CASE importance WHEN 'required' THEN 3 WHEN 'preferred' THEN 2 ELSE 1 END
        THEN excluded.importance ELSE importance END,
    proficiency = CASE
        WHEN excluded.proficiency IS NULL THEN proficiency
        WHEN proficiency IS NULL THEN excluded.proficiency
        WHEN CASE excluded.proficiency WHEN 'expert' THEN 5 WHEN 'advanced' THEN 4
             WHEN 'intermediate' THEN 3 WHEN 'basic' THEN 2 ELSE 1 END
           > CASE proficiency WHEN 'expert' THEN 5 WHEN 'advanced' THEN 4
             WHEN 'intermediate' THEN 3 WHEN 'basic' THEN 2 ELSE 1 END
        THEN excluded.proficiency ELSE proficiency END,
    evidence = CASE
        WHEN evidence IS NULL OR evidence = '' THEN excluded.evidence
        ELSE evidence END,
    confidence = MAX(confidence, excluded.confidence),
    extraction_source = CASE
        WHEN CASE excluded.extraction_source WHEN 'seed' THEN 4 WHEN 'alias' THEN 3
             WHEN 'fuzzy' THEN 2 ELSE 1 END
           > CASE extraction_source WHEN 'seed' THEN 4 WHEN 'alias' THEN 3
             WHEN 'fuzzy' THEN 2 ELSE 1 END
        THEN excluded.extraction_source ELSE extraction_source END,
    verified = MAX(verified, excluded.verified)
"""


def replace_side(
    conn: sqlite3.Connection, analysis_id: str, side: Side, mentions: list[SkillMention]
) -> None:
    """Replace one side's rows inside the caller's transaction."""
    conn.execute(
        "DELETE FROM analysis_skills WHERE analysis_id = ? AND side = ?",
        (analysis_id, side.value),
    )
    now = utc_now()
    for mention in mentions:
        conn.execute(
            _UPSERT,
            (
                analysis_id,
                side.value,
                mention.raw_label,
                mention.canonical_name,
                mention.display_name,
                mention.category,
                mention.importance.value
                if side is Side.JD and mention.importance
                else None,
                mention.proficiency.value
                if side is Side.RESUME and mention.proficiency
                else None,
                mention.evidence,
                mention.confidence,
                mention.extraction_source.value,
                int(mention.verified),
                now,
            ),
        )


def list_side(
    conn: sqlite3.Connection, analysis_id: str, side: Side
) -> list[SkillMention]:
    rows = conn.execute(
        "SELECT raw_label, canonical_name, display_name, category, importance, proficiency, "
        "evidence, confidence, extraction_source, verified FROM analysis_skills "
        "WHERE analysis_id = ? AND side = ? ORDER BY id",
        (analysis_id, side.value),
    ).fetchall()
    return [
        SkillMention(
            side=side,
            raw_label=row["raw_label"],
            canonical_name=row["canonical_name"],
            display_name=row["display_name"],
            category=row["category"],
            importance=Importance(row["importance"]) if row["importance"] else None,
            proficiency=Proficiency(row["proficiency"]) if row["proficiency"] else None,
            evidence=row["evidence"],
            confidence=row["confidence"],
            extraction_source=row["extraction_source"],
            verified=bool(row["verified"]),
        )
        for row in rows
    ]
