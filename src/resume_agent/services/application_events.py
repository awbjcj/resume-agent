"""Application timeline events: validate, sequence, persist, advance status.

Validation is deliberately thin. The real funnel is not a clean sequence --
candidates are referred straight to onsites, recruiters skip the OA, companies
reorder loops -- so ordering is never enforced. A tracker that argues about
what happened is worse than useless. Only vocabulary and required-field
conditions are checked.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from resume_agent.tracking.event_vocab import (
    KIND_IMPLIES_STATUS,
    EventKind,
    EventResult,
    Modality,
    Platform,
)
from resume_agent.tracking.repository import (
    application_for_job,
    delete_application_event,
    events_for_application,
    get_application_event,
    next_sequence,
    resequence_event_kind,
    save_application,
    save_application_event,
)
from resume_agent.tracking.status_rules import advance_application_status
from resume_agent.tracking.tables import Application, ApplicationEvent

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


def _application(session: Session, job_id: int) -> Application:
    existing = application_for_job(session, job_id)
    if existing is not None:
        return existing
    return save_application(session, Application(job_id=job_id), commit=False)


def _advance(session: Session, application: Application, kind: str) -> None:
    implied = KIND_IMPLIES_STATUS.get(kind)
    if implied is None:
        return  # `custom` says nothing about the funnel
    moved = advance_application_status(application.status, implied)
    if moved != application.status:
        application.status = moved
        save_application(session, application, commit=False)


def create_event(
    session: Session, job_id: int, payload: dict[str, Any]
) -> ApplicationEvent:
    _validate(payload)
    try:
        application = _application(session, job_id)
        fields = {k: v for k, v in payload.items() if k in _WRITABLE}
        kind = fields["kind"]
        sequence_overridden = "sequence" in fields
        fields.setdefault("sequence", next_sequence(session, application.id, kind))
        event = save_application_event(
            session,
            ApplicationEvent(
                application_id=application.id,
                sequence_overridden=sequence_overridden,
                **fields,
            ),
            commit=False,
        )
        resequence_event_kind(session, application.id, kind, commit=False)
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
        previous_kind = event.kind
        merged = {field: getattr(event, field) for field in _WRITABLE}
        merged.update({k: v for k, v in payload.items() if k in _WRITABLE})
        _validate(merged)
        for field, value in merged.items():
            setattr(event, field, value)
        if "sequence" in payload:
            event.sequence_overridden = True
        saved = save_application_event(session, event, commit=False)
        resequence_event_kind(session, application.id, previous_kind, commit=False)
        if saved.kind != previous_kind:
            resequence_event_kind(session, application.id, saved.kind, commit=False)
        _advance(session, application, saved.kind)
        session.commit()
        session.refresh(saved)
        return saved
    except BaseException:
        session.rollback()
        raise


def delete_event(session: Session, job_id: int, event_id: int) -> bool:
    """Delete an event. Status is never moved back -- progression is forward-only."""
    application = application_for_job(session, job_id)
    event = get_application_event(session, event_id)
    if application is None or event is None or event.application_id != application.id:
        return False
    kind = event.kind
    try:
        deleted = delete_application_event(session, event_id, commit=False)
        if deleted:
            resequence_event_kind(session, application.id, kind, commit=False)
        session.commit()
        return deleted
    except BaseException:
        session.rollback()
        raise


def list_events(session: Session, job_id: int) -> list[ApplicationEvent]:
    application = application_for_job(session, job_id)
    return (
        [] if application is None else events_for_application(session, application.id)
    )
