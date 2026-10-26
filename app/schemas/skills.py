"""Skill mention and LLM extraction models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CATEGORIES, ExtractionSource, Importance, Proficiency, Side


class LLMSkillBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_label: str = Field(max_length=100)
    canonical_hint: str = Field(max_length=100)
    category: str = Field(default="other", max_length=20)
    evidence: str = Field(default="", max_length=200)


class LLMResumeSkill(LLMSkillBase):
    proficiency: Proficiency = Proficiency.UNKNOWN


class LLMJobSkill(LLMSkillBase):
    importance: Importance = Importance.MENTIONED


class LLMResumeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: list[LLMResumeSkill] = Field(default_factory=list)


class LLMJobExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: list[LLMJobSkill] = Field(default_factory=list)


class SkillMention(BaseModel):
    """One resolved skill mention, ready to persist."""

    model_config = ConfigDict(extra="forbid")

    side: Side
    raw_label: str
    canonical_name: str
    display_name: str
    category: str = "other"
    importance: Importance | None = None
    proficiency: Proficiency | None = None
    evidence: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    extraction_source: ExtractionSource = ExtractionSource.LLM
    verified: bool = True

    @property
    def strength(self) -> float:
        """Resume-side strength used by scoring (spec §11.5)."""
        from app.services.scoring import strength_for_mention

        return strength_for_mention(self)


class ResolvedSkill(BaseModel):
    """A dictionary entry the resolver matched."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    display_name: str
    category: str
    aliases: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    confusables: list[str] = Field(default_factory=list)


class DictionaryEntry(BaseModel):
    canonical_name: str
    display_name: str
    category: str
    aliases: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    confusables: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if self.category not in CATEGORIES:
            object.__setattr__(self, "category", "other")


class SkillSearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    display_name: str
    category: str
    aliases: list[str] = Field(default_factory=list)
