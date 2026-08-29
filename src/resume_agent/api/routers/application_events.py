"""Application timeline CRUD nested under its owning job."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.application_events import (
    ApplicationEventCreate,
    ApplicationEventOut,
    ApplicationEventUpdate,
)
from resume_agent.services.application_events import (
    EventValidationError,
    create_event,
    delete_event,
    list_events,
    update_event,
)
from resume_agent.tracking.repository import get_job

router = APIRouter()


def _require_job(session: Session, job_id: int) -> None:
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")


@router.get("/jobs/{job_id}/events", response_model=list[ApplicationEventOut])
def get_events(job_id: int, session: Session = Depends(get_session)):
    _require_job(session, job_id)
    return list_events(session, job_id)


@router.post(
    "/jobs/{job_id}/events", response_model=ApplicationEventOut, status_code=201
)
def post_event(
    job_id: int,
    body: ApplicationEventCreate,
    session: Session = Depends(get_session),
):
    _require_job(session, job_id)
    try:
        return create_event(session, job_id, body.model_dump(exclude_none=True))
    except EventValidationError as error:
        raise ApiException(422, "VALIDATION_ERROR", error.message) from error


@router.patch("/jobs/{job_id}/events/{event_id}", response_model=ApplicationEventOut)
def patch_event(
    job_id: int,
    event_id: int,
    body: ApplicationEventUpdate,
    session: Session = Depends(get_session),
):
    _require_job(session, job_id)
    try:
        event = update_event(
            session, job_id, event_id, body.model_dump(exclude_unset=True)
        )
    except EventValidationError as error:
        raise ApiException(422, "VALIDATION_ERROR", error.message) from error
    if event is None:
        raise ApiException(404, "NOT_FOUND", f"Event #{event_id} not found")
    return event


@router.delete("/jobs/{job_id}/events/{event_id}", status_code=204)
def remove_event(
    job_id: int, event_id: int, session: Session = Depends(get_session)
) -> Response:
    _require_job(session, job_id)
    if not delete_event(session, job_id, event_id):
        raise ApiException(404, "NOT_FOUND", f"Event #{event_id} not found")
    return Response(status_code=204)
