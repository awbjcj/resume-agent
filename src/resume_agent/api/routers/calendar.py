"""Purpose-bound calendar downloads; no public subscribable feed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.calendar.events import entries_for_upcoming, entry_for_event
from resume_agent.calendar.ics import render_calendar
from resume_agent.tracking.repository import application_for_job, get_application_event, get_job

router = APIRouter()


def _attachment(body: str, filename: str) -> Response:
    return Response(
        content=body.encode("utf-8"),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/events/{event_id}.ics")
def event_ics(
    job_id: int, event_id: int, session: Session = Depends(get_session)
) -> Response:
    job = get_job(session, job_id)
    application = application_for_job(session, job_id)
    event = get_application_event(session, event_id)
    if (
        job is None
        or application is None
        or event is None
        or event.application_id != application.id
    ):
        raise ApiException(404, "NOT_FOUND", "Calendar event not found")
    if event.occurred_at is None:
        raise ApiException(
            422,
            "VALIDATION_ERROR",
            "An undated event cannot be exported to a calendar",
        )
    return _attachment(
        render_calendar([entry_for_event(event, job)]), f"event-{event_id}.ics"
    )


@router.get("/applications/upcoming.ics")
def upcoming_ics(session: Session = Depends(get_session)) -> Response:
    return _attachment(
        render_calendar(entries_for_upcoming(session)),
        "upcoming-application-events.ics",
    )
