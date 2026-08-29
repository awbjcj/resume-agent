from __future__ import annotations

from datetime import datetime

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.api.schemas.coach import CoachSessionSummaryOut
from resume_agent.api.schemas.interview import InterviewSessionSummaryOut


class UpcomingEventOut(CamelModel):
    event_id: int
    job_id: int
    company: str | None = None
    title: str | None = None
    kind: str
    custom_label: str | None = None
    sequence: int
    occurred_at: datetime
    all_day: bool
    timezone: str | None = None
    modality: str | None = None
    platform: str | None = None
    location_or_link: str | None = None


class DashboardSummaryOut(CamelModel):
    status_counts: dict[str, int]
    queues: dict[str, int]
    applied: int
    open_error_count: int = 0
    active_interviews: list[InterviewSessionSummaryOut] = Field(default_factory=list)
    active_coach_session: CoachSessionSummaryOut | None = None
    upcoming_events: list[UpcomingEventOut] = Field(default_factory=list)
