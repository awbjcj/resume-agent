"""User-clearable error records: list, dismiss, and resolve."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.errors import (
    DismissAllOut,
    ErrorRecordOut,
    ErrorRecordsOut,
)
from resume_agent.services.errors import (
    dismiss_all,
    list_error_records,
    set_error_status,
)
from resume_agent.tracking.tables import ErrorRecord

router = APIRouter()
ErrorStatus = Literal["open", "dismissed", "resolved"]


def _row(record: ErrorRecord) -> ErrorRecordOut:
    if record.id is None:
        raise RuntimeError("persisted error record has no id")
    return ErrorRecordOut(
        id=record.id,
        kind=record.kind,
        source_label=record.source_label,
        run_id=record.run_id,
        message=record.message,
        status=record.status,
        count=record.count,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        updated_at=record.updated_at,
    )


@router.get("/errors", response_model=ErrorRecordsOut)
def list_errors(
    status: ErrorStatus = Query("open"),
    session: Session = Depends(get_session),
):
    return ErrorRecordsOut(
        records=[_row(record) for record in list_error_records(session, status)]
    )


def _set_status(
    session: Session, record_id: int, status: Literal["dismissed", "resolved"]
) -> ErrorRecordOut:
    try:
        return _row(set_error_status(session, record_id, status))
    except ValueError as exc:
        message = str(exc)
        if "unknown" in message:
            raise ApiException(404, "NOT_FOUND", message) from exc
        raise ApiException(409, "CONFLICT", message) from exc


@router.post("/errors/dismiss-all", response_model=DismissAllOut)
def dismiss_all_errors(session: Session = Depends(get_session)):
    return DismissAllOut(dismissed=dismiss_all(session))


@router.post("/errors/{record_id}/dismiss", response_model=ErrorRecordOut)
def dismiss_error(record_id: int, session: Session = Depends(get_session)):
    return _set_status(session, record_id, "dismissed")


@router.post("/errors/{record_id}/resolve", response_model=ErrorRecordOut)
def resolve_error(record_id: int, session: Session = Depends(get_session)):
    return _set_status(session, record_id, "resolved")
