"""Persist inbound Gmail status proposals as reviewable notifications."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sqlmodel import Session

from resume_agent.gmail.classify import classify_email
from resume_agent.gmail.client import EmailMessage
from resume_agent.gmail.propose import propose_transitions
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import (
    get_notification,
    notification_by_key,
    pending_notifications,
    save_notification,
    update_application_status,
)
from resume_agent.tracking.tables import Notification


def sync_notifications(
    session: Session,
    emails: Sequence[EmailMessage],
    *,
    classify: Callable[[EmailMessage], str] = classify_email,
) -> list[Notification]:
    for proposal in propose_transitions(emails, application_job_pairs(session), classify):
        if not proposal.message_id:
            continue
        existing = notification_by_key(session, proposal.application_id, proposal.message_id)
        if existing is not None:
            continue
        save_notification(
            session,
            Notification(
                application_id=proposal.application_id,
                kind=proposal.proposed_status,
                proposed_status=proposal.proposed_status,
                evidence=proposal.evidence,
                message_id=proposal.message_id,
            ),
        )
    return pending_notifications(session)


def accept_notification(session: Session, notification_id: int) -> Notification | None:
    notification = get_notification(session, notification_id)
    if notification is None:
        return None
    update_application_status(session, notification.application_id, notification.proposed_status)
    notification.state = "accepted"
    return save_notification(session, notification)


def dismiss_notification(session: Session, notification_id: int) -> Notification | None:
    notification = get_notification(session, notification_id)
    if notification is None:
        return None
    notification.state = "dismissed"
    return save_notification(session, notification)


def list_pending(session: Session) -> list[Notification]:
    return pending_notifications(session)
