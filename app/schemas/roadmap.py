"""Roadmap models and the validation/clamping contract (spec §12.9)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ItemType(StrEnum):
    READ = "read"
    PRACTICE = "practice"
    BUILD = "build"
    ASSESS = "assess"


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=160)
    url: str | None = Field(default=None, max_length=500)
    provider: str = Field(default="Web", max_length=80)
    free: bool = True


class RoadmapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=120)
    type: ItemType = ItemType.READ
    details: str = Field(default="", max_length=400)
    est_minutes: int = Field(default=60, ge=15, le=480)
    resources: list[Resource] = Field(default_factory=list, max_length=3)


class RoadmapWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_number: int = Field(ge=1, le=12)
    theme: str = Field(max_length=80)
    objective: str = Field(max_length=300)
    hours: int = Field(ge=1, le=40)
    focus_skills: list[str] = Field(default_factory=list, max_length=5)
    items: list[RoadmapItem] = Field(min_length=1, max_length=6)


class LLMRoadmap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weeks: list[RoadmapWeek] = Field(default_factory=list)


class Roadmap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weeks: list[RoadmapWeek]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("weeks")
    @classmethod
    def dense_numbering(cls, weeks: list[RoadmapWeek]) -> list[RoadmapWeek]:
        for index, week in enumerate(weeks, start=1):
            if week.week_number != index:
                raise ValueError("weeks must be numbered 1..N in order")
        return weeks
