from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.notifications import NotificationOut
from resume_agent.services.notifications import (
    accept_notification,
    dismiss_notification,
    list_pending,
)

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(session: Session = Depends(get_session)):
    return [NotificationOut.model_validate(n) for n in list_pending(session)]


@router.post("/notifications/{notification_id}/accept", response_model=NotificationOut)
def accept(notification_id: int, session: Session = Depends(get_session)):
    notification = accept_notification(session, notification_id)
    if notification is None:
        raise ApiException(404, "NOT_FOUND", f"Notification #{notification_id} not found")
    return NotificationOut.model_validate(notification)


@router.post("/notifications/{notification_id}/dismiss", response_model=NotificationOut)
def dismiss(notification_id: int, session: Session = Depends(get_session)):
    notification = dismiss_notification(session, notification_id)
    if notification is None:
        raise ApiException(404, "NOT_FOUND", f"Notification #{notification_id} not found")
    return NotificationOut.model_validate(notification)
