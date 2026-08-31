from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.notifications import NotificationOut
from resume_tailor_harness.services.notifications import (
    accept_notification,
    dismiss_notification,
    list_pending,
)
from resume_tailor_harness.tracking.tables import Application, Job

router = APIRouter()


def _to_out(session: Session, notification) -> NotificationOut:
    out = NotificationOut.model_validate(notification)
    application = session.get(Application, notification.application_id)
    if application is not None:
        job = session.get(Job, application.job_id)
        if job is not None:
            return out.model_copy(
                update={"job_id": job.id, "company": job.company, "title": job.title}
            )
    return out


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(session: Session = Depends(get_session)):
    return [_to_out(session, n) for n in list_pending(session)]


@router.post("/notifications/{notification_id}/accept", response_model=NotificationOut)
def accept(notification_id: int, session: Session = Depends(get_session)):
    notification = accept_notification(session, notification_id)
    if notification is None:
        raise ApiException(
            404, "NOT_FOUND", f"Notification #{notification_id} not found"
        )
    return _to_out(session, notification)


@router.post("/notifications/{notification_id}/dismiss", response_model=NotificationOut)
def dismiss(notification_id: int, session: Session = Depends(get_session)):
    notification = dismiss_notification(session, notification_id)
    if notification is None:
        raise ApiException(
            404, "NOT_FOUND", f"Notification #{notification_id} not found"
        )
    return _to_out(session, notification)
