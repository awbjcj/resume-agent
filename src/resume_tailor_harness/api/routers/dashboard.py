from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_interview_dir, get_profile_dir, get_session
from resume_tailor_harness.api.schemas.coach import CoachSessionSummaryOut
from resume_tailor_harness.api.schemas.dashboard import (
    DashboardSummaryOut,
    PracticeStatsOut,
    SourceHealthOut,
    UpcomingEventOut,
)
from resume_tailor_harness.api.schemas.interview import InterviewSessionSummaryOut
from resume_tailor_harness.services.dashboard import (
    summarize_dashboard,
    summarize_practice,
    summarize_source_health,
)
from resume_tailor_harness.services.errors import count_open
from resume_tailor_harness.services.mock_interview import (
    sessions_view as interview_sessions_view,
)
from resume_tailor_harness.services.profile_coach import sessions_view as coach_sessions_view
from resume_tailor_harness.tracking.queries import upcoming_events
from resume_tailor_harness.tracking.event_vocab import INTERVIEW_KINDS

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(request: Request, session: Session = Depends(get_session)):
    summary = summarize_dashboard(session)
    interview_rows = interview_sessions_view(
        get_interview_dir(request), status="active"
    )["sessions"]
    ended_interview_rows = interview_sessions_view(
        get_interview_dir(request), include_archived=True, status="ended"
    )["sessions"]
    practice = summarize_practice(ended_interview_rows)
    source_health = summarize_source_health(session)
    coach_rows = coach_sessions_view(get_profile_dir(request), status="active")[
        "sessions"
    ]
    return DashboardSummaryOut(
        status_counts=summary.status_counts,
        queues=summary.queues,
        applied=summary.applied,
        open_error_count=count_open(session),
        active_interviews=[
            InterviewSessionSummaryOut.model_validate(row) for row in interview_rows
        ],
        active_coach_session=(
            CoachSessionSummaryOut.model_validate(coach_rows[0]) if coach_rows else None
        ),
        practice_stats=PracticeStatsOut.model_validate(practice),
        source_health=SourceHealthOut.model_validate(source_health),
        upcoming_events=[
            UpcomingEventOut(
                event_id=event.id,
                job_id=job.id,
                company=job.company,
                title=job.title,
                kind=event.kind,
                custom_label=event.custom_label,
                sequence=event.sequence,
                occurred_at=event.occurred_at,
                all_day=event.all_day,
                timezone=event.timezone,
                modality=event.modality,
                platform=event.platform,
                location_or_link=event.location_or_link,
            )
            for event, job in upcoming_events(
                session, kinds={*INTERVIEW_KINDS, "offer_deadline"}
            )
            if event.id is not None
            and job.id is not None
            and event.occurred_at is not None
        ],
    )
