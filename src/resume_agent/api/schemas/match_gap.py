"""Match-gap API schemas: missing-skill demand across target jobs."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class GapOut(CamelModel):
    skill: str
    demand_count: int
    target_total: int
    demand_share: int


class MatchGapOut(CamelModel):
    target_total: int
    gaps: list[GapOut]
