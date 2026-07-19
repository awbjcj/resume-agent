from __future__ import annotations

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.api.schemas.coach import CoachSessionSummaryOut
from resume_agent.api.schemas.interview import InterviewSessionSummaryOut


class DashboardSummaryOut(CamelModel):
    status_counts: dict[str, int]
    queues: dict[str, int]
    applied: int
    open_error_count: int = 0
    active_interviews: list[InterviewSessionSummaryOut] = Field(
        default_factory=list
    )
    active_coach_session: CoachSessionSummaryOut | None = None
