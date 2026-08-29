"""Application timeline events: validate, sequence, persist, advance status.

Validation is deliberately thin. The real funnel is not a clean sequence --
candidates are referred straight to onsites, recruiters skip the OA, companies
reorder loops -- so ordering is never enforced. A tracker that argues about
what happened is worse than useless. Only vocabulary and required-field
conditions are checked.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, select

from resume_agent.tracking.event_vocab import (
    KIND_IMPLIES_STATUS,
    EventKind,
    EventResult,
    Modality,
    Platform,
)
from resume_agent.tracking.repository import (
    application_for_job,
    events_for_application,
    get_application_event,
)
from resume_agent.tracking.status_rules import advance_application_status
from resume_agent.tracking.tables import Application, ApplicationEvent, utcnow

logger = logging.getLogger(__name__)

_WRITABLE = {
    "kind",
    "custom_label",
    "sequence",
    "occurred_at",
    "all_day",
    "timezone",
    "duration_minutes",
    "modality",
    "platform",
    "platform_other",
    "location_or_link",
    "interviewers",
    "result",
    "notes",
    "reflection",
    "comp_base",
    "comp_bonus",
    "comp_equity_annual",
    "comp_signing",
    "comp_currency",
    "source",
}


class EventValidationError(Exception):
    """A payload the vocabulary or required-field rules reject."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _validate(payload: dict[str, Any]) -> None:
    kind = payload.get("kind")
    if kind not in {k.value for k in EventKind}:
        raise EventValidationError(f"Unknown event kind '{kind}'")
    if kind == EventKind.custom.value:
        if not (payload.get("custom_label") or "").strip():
            raise EventValidationError("custom_label is required when kind is 'custom'")
    else:
        if payload.get("custom_label") is not None:
            raise EventValidationError(
                "custom_label is only valid when kind is 'custom'"
            )
        if payload.get("occurred_at") is None:
            raise EventValidationError(f"occurred_at is required for kind '{kind}'")

    sequence = payload.get("sequence")
    if sequence is not None and (
        not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
    ):
        raise EventValidationError("sequence must be a positive integer")
    if "all_day" in payload and not isinstance(payload["all_day"], bool):
        raise EventValidationError("all_day must be true or false")

    platform = payload.get("platform")
    if platform is not None and platform not in {p.value for p in Platform}:
        raise EventValidationError(f"Unknown platform '{platform}'")
    if (
        platform == Platform.other.value
        and not (payload.get("platform_other") or "").strip()
    ):
        raise EventValidationError(
            "platform_other is required when platform is 'other'"
        )
    if platform != Platform.other.value and payload.get("platform_other") is not None:
        raise EventValidationError(
            "platform_other is only valid when platform is 'other'"
        )

    modality = payload.get("modality")
    if modality is not None and modality not in {m.value for m in Modality}:
        raise EventValidationError(f"Unknown modality '{modality}'")

    result = payload.get("result")
    if result is not None and result not in {r.value for r in EventResult}:
        raise EventValidationError(f"Unknown result '{result}'")

    timezone = payload.get("timezone")
    if timezone:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as error:
            raise EventValidationError(f"Unknown IANA timezone '{timezone}'") from error


def _application(session: Session, job_id: int) -> Application:
    existing = application_for_job(session, job_id)
    if existing is not None:
        return existing
    application = Application(job_id=job_id)
    session.add(application)
    session.flush()
    return application


def _advance(session: Session, application: Application, kind: str) -> None:
    implied = KIND_IMPLIES_STATUS.get(kind)
    if implied is None:
        return  # `custom` says nothing about the funnel
    moved = advance_application_status(application.status, implied)
    if moved != application.status:
        application.status = moved
        if moved == "submitted" and application.submitted_at is None:
            application.submitted_at = utcnow()
        session.add(application)


def _sort_moment(value: datetime | None) -> datetime:
    if value is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _resequence_group(session: Session, application_id: int, kind: str) -> None:
    """Recompute effective order while reserving every explicit override."""
    events = list(
        session.exec(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == application_id,
                ApplicationEvent.kind == kind,
            )
        ).all()
    )
    occupied = {
        item.sequence_override for item in events if item.sequence_override is not None
    }
    for item in events:
        if item.sequence_override is not None:
            item.sequence = item.sequence_override
            session.add(item)

    automatic = sorted(
        (item for item in events if item.sequence_override is None),
        key=lambda item: (
            _sort_moment(item.occurred_at),
            _sort_moment(item.created_at),
            item.id or 0,
        ),
    )
    next_sequence = 1
    for item in automatic:
        while next_sequence in occupied:
            next_sequence += 1
        item.sequence = next_sequence
        session.add(item)
        next_sequence += 1


def _warn_duplicate_override(session: Session, event: ApplicationEvent) -> None:
    """Log the spec-permitted collision without blocking the write."""
    if event.sequence_override is None:
        return
    statement = select(ApplicationEvent).where(
        ApplicationEvent.application_id == event.application_id,
        ApplicationEvent.kind == event.kind,
        ApplicationEvent.sequence_override == event.sequence_override,
    )
    if event.id is not None:
        statement = statement.where(ApplicationEvent.id != event.id)
    if session.exec(statement).first() is not None:
        logger.warning(
            "Duplicate application event key application_id=%s kind=%s sequence=%s",
            event.application_id,
            event.kind,
            event.sequence_override,
        )


def create_event(
    session: Session, job_id: int, payload: dict[str, Any]
) -> ApplicationEvent:
    _validate(payload)
    try:
        application = _application(session, job_id)
        fields = {k: v for k, v in payload.items() if k in _WRITABLE}
        if fields.get("occurred_at") is not None:
            fields["occurred_at"] = fields["occurred_at"].astimezone(timezone.utc)
        kind = fields["kind"]
        application_id = application.id
        if application_id is None:
            raise RuntimeError("Application id was not assigned")
        sequence_override = fields.pop("sequence", None)
        event = ApplicationEvent(
            application_id=application_id,
            sequence=sequence_override or 1,
            sequence_override=sequence_override,
            **fields,
        )
        _warn_duplicate_override(session, event)
        event.updated_at = utcnow()
        session.add(event)
        session.flush()
        _resequence_group(session, application_id, kind)
        _advance(session, application, kind)
        session.commit()
        session.refresh(event)
        return event
    except BaseException:
        session.rollback()
        raise


def update_event(
    session: Session, job_id: int, event_id: int, payload: dict[str, Any]
) -> ApplicationEvent | None:
    application = application_for_job(session, job_id)
    event = get_application_event(session, event_id)
    if application is None or event is None or event.application_id != application.id:
        return None
    try:
        old_kind = event.kind
        sequence_supplied = "sequence" in payload
        sequence_override = payload.get("sequence") if sequence_supplied else None
        if sequence_override is not None and (
            not isinstance(sequence_override, int)
            or isinstance(sequence_override, bool)
            or sequence_override < 1
        ):
            raise EventValidationError("sequence must be a positive integer")
        merged = {field: getattr(event, field) for field in _WRITABLE}
        merged.update(
            {k: v for k, v in payload.items() if k in _WRITABLE and k != "sequence"}
        )
        if payload.get("occurred_at") is not None:
            merged["occurred_at"] = payload["occurred_at"].astimezone(timezone.utc)
        _validate(merged)
        for field, value in merged.items():
            setattr(event, field, value)
        if sequence_supplied:
            event.sequence_override = sequence_override
        event.updated_at = utcnow()
        session.add(event)
        session.flush()
        _warn_duplicate_override(session, event)
        application_id = event.application_id
        for kind in {old_kind, event.kind}:
            _resequence_group(session, application_id, kind)
        _advance(session, application, event.kind)
        session.commit()
        session.refresh(event)
        return event
    except BaseException:
        session.rollback()
        raise


def delete_event(session: Session, job_id: int, event_id: int) -> bool:
    """Delete an event. Status is never moved back -- progression is forward-only."""
    application = application_for_job(session, job_id)
    event = get_application_event(session, event_id)
    if application is None or event is None or event.application_id != application.id:
        return False
    try:
        application_id = event.application_id
        kind = event.kind
        session.delete(event)
        session.flush()
        _resequence_group(session, application_id, kind)
        session.commit()
        return True
    except BaseException:
        session.rollback()
        raise


def list_events(session: Session, job_id: int) -> list[ApplicationEvent]:
    application = application_for_job(session, job_id)
    if application is None or application.id is None:
        return []
    return events_for_application(session, application.id)
