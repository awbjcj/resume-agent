from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_interview_dir, get_profile_dir, get_session
from resume_agent.api.schemas.coach import CoachSessionSummaryOut
from resume_agent.api.schemas.dashboard import DashboardSummaryOut
from resume_agent.api.schemas.interview import InterviewSessionSummaryOut
from resume_agent.services.dashboard import summarize_dashboard
from resume_agent.services.errors import count_open
from resume_agent.services.mock_interview import sessions_view as interview_sessions_view
from resume_agent.services.profile_coach import sessions_view as coach_sessions_view

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    request: Request, session: Session = Depends(get_session)
):
    summary = summarize_dashboard(session)
    interview_rows = interview_sessions_view(
        get_interview_dir(request), status="active"
    )["sessions"]
    coach_rows = coach_sessions_view(get_profile_dir(request), status="active")[
        "sessions"
    ]
    return DashboardSummaryOut(
        status_counts=summary.status_counts,
        queues=summary.queues,
        applied=summary.applied,
        open_error_count=count_open(session),
        active_interviews=[
            InterviewSessionSummaryOut.model_validate(row)
            for row in interview_rows
        ],
        active_coach_session=(
            CoachSessionSummaryOut.model_validate(coach_rows[0])
            if coach_rows
            else None
        ),
    )
