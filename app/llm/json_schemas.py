"""JSON Schemas for the three model calls (spec §12.7–§12.9).

Every schema forbids additional properties and bounds every string, so a successful
prompt injection still has nowhere to put its output (§12.12 rule 4).
"""

from __future__ import annotations

from typing import Any

CATEGORY_ENUM = [
    "language",
    "framework",
    "database",
    "cloud",
    "devops",
    "data",
    "ml",
    "frontend",
    "backend",
    "mobile",
    "testing",
    "tool",
    "soft",
    "domain",
    "other",
]

PROFICIENCY_ENUM = ["expert", "advanced", "intermediate", "basic", "unknown"]
IMPORTANCE_ENUM = ["required", "preferred", "mentioned"]
ITEM_TYPE_ENUM = ["read", "practice", "build", "assess"]

RESUME_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["skills"],
    "properties": {
        "skills": {
            "type": "array",
            "maxItems": 60,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_label", "canonical_hint", "category", "proficiency", "evidence"],
                "properties": {
                    "raw_label": {"type": "string", "maxLength": 100},
                    "canonical_hint": {"type": "string", "maxLength": 100},
                    "category": {"type": "string", "enum": CATEGORY_ENUM},
                    "proficiency": {"type": "string", "enum": PROFICIENCY_ENUM},
                    "evidence": {"type": "string", "maxLength": 200},
                },
            },
        }
    },
}

JD_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["skills"],
    "properties": {
        "skills": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_label", "canonical_hint", "category", "importance", "evidence"],
                "properties": {
                    "raw_label": {"type": "string", "maxLength": 100},
                    "canonical_hint": {"type": "string", "maxLength": 100},
                    "category": {"type": "string", "enum": CATEGORY_ENUM},
                    "importance": {"type": "string", "enum": IMPORTANCE_ENUM},
                    "evidence": {"type": "string", "maxLength": 200},
                },
            },
        }
    },
}

ROADMAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["weeks"],
    "properties": {
        "weeks": {
            "type": "array",
            "minItems": 2,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["week_number", "theme", "objective", "hours", "focus_skills", "items"],
                "properties": {
                    "week_number": {"type": "integer", "minimum": 1, "maximum": 12},
                    "theme": {"type": "string", "maxLength": 80},
                    "objective": {"type": "string", "maxLength": 300},
                    "hours": {"type": "integer", "minimum": 1, "maximum": 40},
                    "focus_skills": {
                        "type": "array",
                        "maxItems": 5,
                        "items": {"type": "string", "maxLength": 60},
                    },
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title", "type", "details", "est_minutes", "resources"],
                            "properties": {
                                "title": {"type": "string", "maxLength": 120},
                                "type": {"type": "string", "enum": ITEM_TYPE_ENUM},
                                "details": {"type": "string", "maxLength": 400},
                                "est_minutes": {"type": "integer", "minimum": 15, "maximum": 480},
                                "resources": {
                                    "type": "array",
                                    "maxItems": 3,
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["label", "provider", "free"],
                                        "properties": {
                                            "label": {"type": "string", "maxLength": 160},
                                            "url": {"type": "string", "maxLength": 500},
                                            "provider": {"type": "string", "maxLength": 80},
                                            "free": {"type": "boolean"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "resume_extraction": RESUME_EXTRACTION_SCHEMA,
    "jd_extraction": JD_EXTRACTION_SCHEMA,
    "roadmap": ROADMAP_SCHEMA,
}
