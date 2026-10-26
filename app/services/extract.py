"""The two extraction stages plus the degraded keyword fallback (spec §12.7–§12.10)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings
from app.errors import AppError
from app.llm.client import OpenRouterClient
from app.llm.dto import LLMRequest
from app.llm.json_schemas import JD_EXTRACTION_SCHEMA, RESUME_EXTRACTION_SCHEMA
from app.llm.prompts import (
    EXTRACT_MAX_TOKENS,
    EXTRACT_TEMPERATURE,
    PROMPT_VERSION_EXTRACT,
    render_jd_extraction,
    render_resume_extraction,
)
from app.schemas.common import ExtractionSource, Side, Stage
from app.schemas.skills import (
    LLMJobExtraction,
    LLMResumeExtraction,
    SkillMention,
)
from app.services.keyword_scan import DictionaryScanner
from app.services.normalization import SkillResolver, resolve_mention

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionOutcome:
    mentions: list[SkillMention] = field(default_factory=list)
    degraded: bool = False
    warning: str | None = None
    model: str | None = None


def degraded_scan(
    text: str, side: Side, resolver: SkillResolver, settings: Settings
) -> ExtractionOutcome:
    """Keyword-only extraction (§12.10): seed-sourced, unverified, no evidence claims."""
    scanner = DictionaryScanner(resolver)
    mentions: list[SkillMention] = []
    for hit in scanner.scan(text, side):
        # ``verified=0`` and seed provenance are what mark this mode in the UI.
        mentions.append(
            hit.model_copy(
                update={
                    "verified": False,
                    "confidence": 0.6,
                    "extraction_source": ExtractionSource.SEED,
                }
            )
        )
    return ExtractionOutcome(mentions=mentions, degraded=True)


def _mentions_from_resume(payload: dict, resolver: SkillResolver) -> list[SkillMention]:
    extraction = LLMResumeExtraction.model_validate(payload)
    mentions: list[SkillMention] = []
    for skill in extraction.skills:
        mention = resolve_mention(
            resolver,
            side=Side.RESUME,
            raw_label=skill.raw_label,
            canonical_hint=skill.canonical_hint,
            category=skill.category,
            proficiency=skill.proficiency,
            evidence=skill.evidence,
        )
        if mention is not None:
            mentions.append(mention)
    return mentions


def _mentions_from_jd(payload: dict, resolver: SkillResolver) -> list[SkillMention]:
    extraction = LLMJobExtraction.model_validate(payload)
    mentions: list[SkillMention] = []
    for skill in extraction.skills:
        mention = resolve_mention(
            resolver,
            side=Side.JD,
            raw_label=skill.raw_label,
            canonical_hint=skill.canonical_hint,
            category=skill.category,
            importance=skill.importance,
            evidence=skill.evidence,
        )
        if mention is not None:
            mentions.append(mention)
    return mentions


async def extract_resume(
    text: str,
    *,
    settings: Settings,
    resolver: SkillResolver,
    client: OpenRouterClient | None,
    conn_factory,
    analysis_id: str | None = None,
    job_id: str | None = None,
) -> ExtractionOutcome:
    """LLM extraction with a keyword fallback on any upstream failure (§12.10)."""
    if not settings.llm_available or client is None:
        return degraded_scan(text, Side.RESUME, resolver, settings)

    system, user = render_resume_extraction(text)
    request = LLMRequest(
        stage=Stage.EXTRACT_RESUME,
        model=settings.OPENROUTER_MODEL_EXTRACT,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=EXTRACT_TEMPERATURE,
        max_tokens=EXTRACT_MAX_TOKENS,
        prompt_version=PROMPT_VERSION_EXTRACT,
        timeout_s=settings.LLM_TIMEOUT_EXTRACT_S,
        cache_input=text,
        json_schema=RESUME_EXTRACTION_SCHEMA,
        schema_name="resume_extraction",
        analysis_id=analysis_id,
        job_id=job_id,
    )
    try:
        result = await client.complete(request, LLMResumeExtraction, conn_factory)
    except AppError as exc:
        logger.warning("Resume extraction fell back to keywords: %s", exc.code)
        outcome = degraded_scan(text, Side.RESUME, resolver, settings)
        return ExtractionOutcome(
            mentions=outcome.mentions,
            degraded=True,
            warning=exc.code,
            model=settings.OPENROUTER_MODEL_EXTRACT,
        )

    return ExtractionOutcome(
        mentions=_mentions_from_resume(result.payload, resolver),
        model=result.model_resolved,
    )


async def extract_jd(
    text: str,
    *,
    settings: Settings,
    resolver: SkillResolver,
    client: OpenRouterClient | None,
    conn_factory,
    analysis_id: str | None = None,
    job_id: str | None = None,
) -> ExtractionOutcome:
    if not settings.llm_available or client is None:
        return degraded_scan(text, Side.JD, resolver, settings)

    system, user = render_jd_extraction(text)
    request = LLMRequest(
        stage=Stage.EXTRACT_JD,
        model=settings.OPENROUTER_MODEL_EXTRACT,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=EXTRACT_TEMPERATURE,
        max_tokens=EXTRACT_MAX_TOKENS,
        prompt_version=PROMPT_VERSION_EXTRACT,
        timeout_s=settings.LLM_TIMEOUT_EXTRACT_S,
        cache_input=text,
        json_schema=JD_EXTRACTION_SCHEMA,
        schema_name="jd_extraction",
        analysis_id=analysis_id,
        job_id=job_id,
    )
    try:
        result = await client.complete(request, LLMJobExtraction, conn_factory)
    except AppError as exc:
        logger.warning("JD extraction fell back to keywords: %s", exc.code)
        outcome = degraded_scan(text, Side.JD, resolver, settings)
        return ExtractionOutcome(
            mentions=outcome.mentions,
            degraded=True,
            warning=exc.code,
            model=settings.OPENROUTER_MODEL_EXTRACT,
        )

    return ExtractionOutcome(
        mentions=_mentions_from_jd(result.payload, resolver),
        model=result.model_resolved,
    )
