"""Server-rendered pages: the SPA shell, its no-JS results, history, and the dashboard.

Only presentation lives here. Every read goes through the same repositories the JSON
API uses, so a page can never show a number the API would not return.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.repositories import analyses_repo, gaps_repo, roadmap_repo
from app.dependencies import get_db, get_settings
from app.schemas.scoring import BAND_LABELS, Band

router = APIRouter(tags=["pages"])

#: Newest N analyses the dashboard's activity tiles summarise over.
DASHBOARD_WINDOW = 20


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _band_label(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return BAND_LABELS[Band(value)]
    except ValueError:
        return value.replace("_", " ")


def _dashboard_summary(conn: sqlite3.Connection) -> dict:
    """Headline numbers for the dashboard, over the most recent analyses.

    Deliberately descriptive: averages and counts of what is already stored, never a
    derived "readiness" score of our own invention.
    """
    records, total = analyses_repo.list_page(conn, limit=DASHBOARD_WINDOW, offset=0)
    scored = [record for record in records if record.match_score is not None]
    gaps = analyses_repo.gap_counts(conn, [record.id for record in records])
    return {
        "total": total,
        "window": len(records),
        "scored": len(scored),
        "average_score": round(sum(r.match_score for r in scored) / len(scored)) if scored else None,
        "best_score": max((r.match_score for r in scored), default=None),
        "open_gaps": sum(gaps.get(r.id, 0) for r in records),
        "span_label": _span_label(records),
    }


def _span_label(records: list) -> str | None:
    """``23 Oct – 26 Oct 2026`` for the window, or ``26 Oct 2026`` for a single day."""
    if not records:
        return None
    stamps = []
    for record in records:
        try:
            stamps.append(datetime.fromisoformat(str(record.created_at).replace("Z", "+00:00")))
        except ValueError:
            continue
    if not stamps:
        return None
    newest, oldest = max(stamps), min(stamps)
    if newest.date() == oldest.date():
        return newest.strftime("%d %b %Y").lstrip("0")
    if (newest.year, newest.month) == (oldest.year, oldest.month):
        return f"{oldest.strftime('%d').lstrip('0')} – {newest.strftime('%d %b %Y').lstrip('0')}"
    return f"{oldest.strftime('%d %b').lstrip('0')} – {newest.strftime('%d %b %Y').lstrip('0')}"


def _top_gaps(conn: sqlite3.Connection, analysis_ids: list[str]) -> dict[str, str]:
    """First gap per analysis, in one query (the list view shows it as a hint)."""
    if not analysis_ids:
        return {}
    placeholders = ", ".join(["?"] * len(analysis_ids))
    rows = conn.execute(
        f"SELECT analysis_id, display_name FROM skill_gaps "
        f"WHERE analysis_id IN ({placeholders}) AND sort_order = 1",
        tuple(analysis_ids),
    ).fetchall()
    return {row["analysis_id"]: row["display_name"] for row in rows}


def _history_items(conn: sqlite3.Connection, records: list) -> list[dict]:
    """Rows of the analysis-history view, carrying what the card/table renders."""
    gap_counts = analyses_repo.gap_counts(conn, [record.id for record in records])
    top_gaps = _top_gaps(conn, [record.id for record in records])
    items = []
    for record in records:
        items.append(
            {
                "record": record,
                "band_label": _band_label(record.match_band),
                "gap_count": gap_counts.get(record.id, 0),
                "top_gap": top_gaps.get(record.id),
            }
        )
    return items


def _base_context(request: Request, **extra) -> dict:
    context = {
        "request": request,
        "settings": get_settings(),
        "page_title": "SkillMirror",
        "active_page": None,
    }
    context.update(extra)
    return context


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    analysis: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
):
    context = _base_context(
        request,
        analysis=None,
        gaps=[],
        weeks=[],
        recent=[],
        roadmap_generated_at=None,
        error=None,
        page_title="SkillMirror",
        active_page="dashboard",
    )
    if analysis:
        record = analyses_repo.get(conn, analysis)
        if record is None:
            context["error"] = "That analysis no longer exists."
        else:
            context["analysis"] = record
            context["gaps"] = gaps_repo.list_for(conn, analysis)
            context["weeks"] = roadmap_repo.list_for(conn, analysis)
            context["roadmap_generated_at"] = roadmap_repo.generated_at(conn, analysis)
            context["page_title"] = f"{record.role_label} — SkillMirror"
            context["active_page"] = "history"

    records, _total = analyses_repo.list_page(conn, limit=5, offset=0)
    context["recent"] = _history_items(conn, records)
    context["summary"] = _dashboard_summary(conn)
    return _templates(request).TemplateResponse(request, "index.html", context)


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    records, total = analyses_repo.list_page(conn, limit=20, offset=0)
    items = _history_items(conn, records)
    scored = [item for item in items if item["record"].match_score is not None]
    return _templates(request).TemplateResponse(
        request,
        "history.html",
        _base_context(
            request,
            items=items,
            total=total,
            active_page="history",
            page_title="Analysis history — SkillMirror",
            history_stats={
                "count": total,
                "scored": len(scored),
                "average_score": (
                    round(sum(i["record"].match_score for i in scored) / len(scored))
                    if scored
                    else None
                ),
                "open_gaps": sum(item["gap_count"] for item in items),
            },
        ),
    )


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return _templates(request).TemplateResponse(
        request,
        "help.html",
        _base_context(request, active_page="help", page_title="Help — SkillMirror"),
    )
