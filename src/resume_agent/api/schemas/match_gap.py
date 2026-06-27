"""Match-gap API schemas for the skill-demand graph."""

from __future__ import annotations

from typing import Literal

from resume_agent.api.schemas.base import CamelModel


class GapOut(CamelModel):
    """Legacy projection retained until the router migrates in Task 7."""

    skill: str
    demand_count: int
    target_total: int
    demand_share: int


class JobLiteOut(CamelModel):
    id: int
    company: str | None = None
    title: str | None = None
    seniority: str | None = None


class SkillNodeOut(CamelModel):
    skill: str
    theme_id: str | None = None
    covered: bool


class DemandEdgeOut(CamelModel):
    job_id: int
    skill: str
    source: Literal["must", "nice", "tech"]


class ThemeOut(CamelModel):
    id: str
    label: str


class MatchGapOut(CamelModel):
    target_total: int
    clusters_stale: bool
    jobs: list[JobLiteOut]
    skills: list[SkillNodeOut]
    edges: list[DemandEdgeOut]
    themes: list[ThemeOut]
