"""The single Jinja environment shared by every page (spec §6, §7.9).

Building one ``Jinja2Templates`` at startup (rather than per request) means templates
are parsed and cached once, and every page sees the same globals and filters.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.schemas.common import Band
from app.schemas.scoring import BAND_LABELS

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_BAND_BY_VALUE = {band.value: label for band, label in BAND_LABELS.items()}

_PRIORITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

_STATUS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "completed": "Completed",
    "partial": "Partial",
    "failed": "Failed",
}

_HUMAN_IMPORTANCE = {
    "required": "Required",
    "preferred": "Preferred",
    "mentioned": "Mentioned",
}


def _band_label(value: str | None) -> str:
    if not value:
        return "Not scored"
    return _BAND_BY_VALUE.get(str(value), str(value))


def _humanize(value: str | None) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").strip().capitalize()


def _hours(value: int | float | None) -> str:
    if value is None:
        return "—"
    minutes = int(round(float(value) * 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, remainder = divmod(minutes, 60)
    if remainder and hours < 10:
        return f"{hours}h {remainder}m"
    return f"{hours}h"


def _minutes(value: int | float | None) -> str:
    """Minutes as the roadmap stores them: ``90`` → ``1h 30m``."""
    if value is None:
        return "—"
    total = int(value)
    if total < 60:
        return f"{total} min"
    hours, remainder = divmod(total, 60)
    return f"{hours}h {remainder}m" if remainder else f"{hours}h"


def _percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{round(float(value) * 100)}%"


def _short_date(value: str | None) -> str:
    """``2026-10-23T14:02:11.482Z`` → ``23 Oct 2026``."""
    if not value:
        return ""
    try:
        from datetime import datetime

        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    return stamp.strftime("%d %b %Y").lstrip("0")


def build_templates(settings: Settings, meta: dict) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    env = templates.env
    env.globals.update(
        settings=settings,
        meta=meta,
        band_label=_band_label,
        priority_labels=_PRIORITY_LABELS,
        status_labels=_STATUS_LABELS,
        importance_labels=_HUMAN_IMPORTANCE,
        score_formula="score = round(100 × Σ(weight × strength) / Σ(weight))",
    )
    env.filters["band_label"] = _band_label
    env.filters["humanize"] = _humanize
    env.filters["hours"] = _hours
    env.filters["minutes"] = _minutes
    env.filters["percent"] = _percent
    env.filters["short_date"] = _short_date
    return templates


def bands_for(meta: dict) -> list[dict]:
    return list(meta.get("bands", []))


__all__ = ["TEMPLATES_DIR", "build_templates", "bands_for", "Band"]
