"""Deterministic stale-application reminders. No LLM, no email parsing.

One reminder per staleness episode: the dedupe key embeds the
application's last-activity date, so a dismissal stays dismissed until
real activity bumps updated_at and a new episode begins.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, select

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.tracking.event_vocab import EventKind, EventResult
from resume_tailor_harness.tracking.queries import application_job_pairs, reminder_event_job_rows
from resume_tailor_harness.tracking.repository import notification_by_key, save_notification
from resume_tailor_harness.tracking.tables import Notification, utcnow

FOLLOW_UP_KIND = "follow_up"
_STALE_STATUSES = {"submitted", "interview"}
INTERVIEW_KIND = "interview_soon"
DEADLINE_KIND = "offer_deadline_soon"
_REMINDABLE_INTERVIEW_KINDS = {
    EventKind.recruiter_screen.value,
    EventKind.online_assessment.value,
    EventKind.questionnaire.value,
    EventKind.technical_phone_screen.value,
    EventKind.technical_round.value,
    EventKind.system_design.value,
    EventKind.behavioral.value,
    EventKind.hiring_manager.value,
    EventKind.onsite_loop.value,
    EventKind.team_match.value,
}
_DEAD_RESULTS = {EventResult.cancelled.value, EventResult.withdrew.value}


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


def event_reminder_key(event_id: int, occurred_at: datetime, kind: str) -> str:
    """Date-keyed episode: rescheduling creates a fresh reminder."""
    return f"{kind}:{event_id}:{_aware(occurred_at).isoformat()}"


def create_event_reminders(
    session: Session,
    *,
    now: datetime | None = None,
    interview_hours: int | None = None,
    deadline_days: int | None = None,
) -> list[Notification]:
    settings = get_settings()
    interview_hours = (
        settings.interview_reminder_hours
        if interview_hours is None
        else interview_hours
    )
    deadline_days = (
        settings.offer_deadline_reminder_days
        if deadline_days is None
        else deadline_days
    )
    current = _aware(now or utcnow())
    created: list[Notification] = []
    windows = (
        (
            INTERVIEW_KIND,
            _REMINDABLE_INTERVIEW_KINDS,
            timedelta(hours=interview_hours),
        ),
        (
            DEADLINE_KIND,
            {EventKind.offer_deadline.value},
            timedelta(days=deadline_days),
        ),
    )
    active_windows = [item for item in windows if item[2] > timedelta(0)]
    if not active_windows:
        return []
    widest = max(window for _, _, window in active_windows)
    kinds = {
        event_kind for _, event_kinds, _ in active_windows for event_kind in event_kinds
    }
    rows = reminder_event_job_rows(
        session,
        after=current,
        before=current + widest,
        kinds=kinds,
        dead_results=_DEAD_RESULTS,
    )
    candidate_rows: list[tuple[int, str, Notification]] = []
    for event, application, job in rows:
        if event.id is None or application.id is None or event.occurred_at is None:
            continue
        occurred = _aware(event.occurred_at)
        if occurred <= current:
            continue
        for kind, event_kinds, window in active_windows:
            if event.kind not in event_kinds or window <= timedelta(0):
                continue
            if occurred - current > window:
                continue
            key = event_reminder_key(event.id, occurred, kind)
            label = "Offer deadline" if kind == DEADLINE_KIND else "Interview"
            candidate_rows.append(
                (
                    application.id,
                    key,
                    Notification(
                        application_id=application.id,
                        kind=kind,
                        proposed_status="",
                        evidence=(
                            f"{label} {occurred.strftime('%b %d, %H:%M UTC')} — "
                            f"{job.company} · {job.title}"
                        ),
                        message_id=key,
                    ),
                )
            )
    if not candidate_rows:
        return []
    application_ids = {application_id for application_id, _, _ in candidate_rows}
    keys = {key for _, key, _ in candidate_rows}
    existing = set(
        session.exec(
            select(Notification.application_id, Notification.message_id).where(
                col(Notification.application_id).in_(application_ids),
                col(Notification.message_id).in_(keys),
            )
        ).all()
    )
    created = [
        notification
        for application_id, key, notification in candidate_rows
        if (application_id, key) not in existing
    ]
    if created:
        session.add_all(created)
        session.commit()
        for notification in created:
            session.refresh(notification)
    return created
