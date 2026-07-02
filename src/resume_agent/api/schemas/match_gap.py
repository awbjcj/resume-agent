"""Match-gap API schemas for the skill-demand graph."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from resume_agent.api.schemas.base import CamelModel


class JobLiteOut(CamelModel):
    id: int
    company: str | None = None
    title: str | None = None
    seniority: str | None = None


class SkillNodeOut(CamelModel):
    skill: str
    theme_id: str | None = None
    covered: bool
    coverage: Literal["covered", "adjacent", "gap"] = "gap"
    key: str
    members: dict[str, int]
    must: int
    nice: int
    tech: int
    job_count: int

    @model_validator(mode="after")
    def sync_legacy_covered(self) -> "SkillNodeOut":
        if self.covered or self.coverage == "covered":
            self.covered = True
            self.coverage = "covered"
        else:
            self.covered = False
        return self


class DemandEdgeOut(CamelModel):
    job_id: int
    skill: str
    source: Literal["must", "nice", "tech"]
    skill_key: str


class ThemeOut(CamelModel):
    id: str
    label: str
    essential_score: int
    popular_score: int
    job_count: int
    skill_count: int
    gap_count: int
    adjacent_count: int = 0


class SuggestionStatusOut(CamelModel):
    kind: Literal["skill", "theme"]
    key: str
    state: Literal["ready", "stale"]
    generated_at: datetime


class MatchGapOut(CamelModel):
    target_total: int
    clusters_stale: bool
    jobs: list[JobLiteOut]
    skills: list[SkillNodeOut]
    edges: list[DemandEdgeOut]
    themes: list[ThemeOut]
    suggestion_statuses: list[SuggestionStatusOut] = Field(default_factory=list)
