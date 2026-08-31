"""Map application events onto pure calendar entries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_tailor_harness.calendar.ics import CalendarEntry
from resume_tailor_harness.tracking.event_vocab import REPEATABLE_KINDS
from resume_tailor_harness.tracking.queries import upcoming_events
from resume_tailor_harness.tracking.tables import ApplicationEvent, Job, utcnow

KIND_LABELS = {
    "application_submitted": "Application submitted",
    "recruiter_screen": "Recruiter screen",
    "online_assessment": "Online assessment",
    "questionnaire": "Questionnaire",
    "technical_phone_screen": "Technical phone screen",
    "technical_round": "Technical round",
    "system_design": "System design",
    "behavioral": "Behavioral",
    "hiring_manager": "Hiring manager",
    "onsite_loop": "Onsite loop",
    "team_match": "Team match",
    "offer_received": "Offer received",
    "offer_deadline": "Offer deadline",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "custom": "Other",
}
PLATFORM_LABELS = {
    "zoom": "Zoom",
    "teams": "Microsoft Teams",
    "google_meet": "Google Meet",
    "webex": "Webex",
    "tencent_meeting": "Tencent Meeting",
    "feishu": "Feishu",
    "phone": "Phone",
    "hackerrank": "HackerRank",
    "codesignal": "CodeSignal",
    "coderpad": "CoderPad",
    "karat": "Karat",
    "other": "Other",
}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def entry_for_event(event: ApplicationEvent, job: Job) -> CalendarEntry:
    if event.occurred_at is None:
        raise ValueError("An undated event cannot be exported")
    label = event.custom_label if event.kind == "custom" else KIND_LABELS[event.kind]
    if event.kind in REPEATABLE_KINDS:
        label = f"{label} {event.sequence}"
    platform = (
        event.platform_other
        if event.platform == "other"
        else PLATFORM_LABELS.get(event.platform or "")
    )
    description = (
        "\n".join(
            value
            for value in (
                f"Interviewers: {event.interviewers}" if event.interviewers else None,
                f"Platform: {platform}" if platform else None,
                f"Modality: {event.modality}" if event.modality else None,
                event.notes,
            )
            if value
        )
        or None
    )
    is_url = (event.location_or_link or "").startswith(("http://", "https://"))
    start = _aware(event.occurred_at)
    end = (
        start + timedelta(minutes=event.duration_minutes)
        if event.duration_minutes and not event.all_day
        else None
    )
    return CalendarEntry(
        uid=f"application-event-{event.id}@resume-tailor-harness",
        summary=f"{label} — {job.company or 'Company'}",
        start=start,
        end=end,
        all_day=event.all_day,
        timezone=event.timezone,
        location=event.location_or_link,
        url=event.location_or_link if is_url else None,
        description=description,
        alarm_minutes_before=None if event.all_day else 60,
    )


def entries_for_upcoming(
    session: Session,
    *,
    now: datetime | None = None,
    within_days: int = 90,
) -> list[CalendarEntry]:
    current = now or utcnow()
    return [
        entry_for_event(event, job)
        for event, job in upcoming_events(session, within_days=within_days, now=current)
    ]
