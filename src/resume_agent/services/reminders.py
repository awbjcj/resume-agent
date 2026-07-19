"""Deterministic stale-application reminders. No LLM, no email parsing.

One reminder per staleness episode: the dedupe key embeds the
application's last-activity date, so a dismissal stays dismissed until
real activity bumps updated_at and a new episode begins.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import notification_by_key, save_notification
from resume_agent.tracking.tables import Notification, utcnow

FOLLOW_UP_KIND = "follow_up"
_STALE_STATUSES = {"submitted", "interview"}


def follow_up_key(application_id: int, anchor: datetime) -> str:
    return f"followup:{application_id}:{anchor.date().isoformat()}"


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def create_follow_up_reminders(
    session: Session,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> list[Notification]:
    days = get_settings().follow_up_days if days is None else days
    if days <= 0:
        return []
    now = _aware(now or utcnow())
    created: list[Notification] = []
    for app, job in application_job_pairs(session):
        if app.id is None or app.status not in _STALE_STATUSES:
            continue
        anchor = _aware(app.updated_at)
        if now - anchor < timedelta(days=days):
            continue
        key = follow_up_key(app.id, anchor)
        if notification_by_key(session, app.id, key) is not None:
            continue
        created.append(
            save_notification(
                session,
                Notification(
                    application_id=app.id,
                    kind=FOLLOW_UP_KIND,
                    proposed_status="",
                    evidence=(
                        f"No activity for {(now - anchor).days} days — "
                        f"{job.company} · {job.title}"
                    ),
                    message_id=key,
                ),
            )
        )
    return created
