"""User-clearable error records: list, dismiss, and resolve."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.base import Pagination
from resume_agent.api.schemas.errors import (
    DismissAllOut,
    ErrorRecordOut,
    ErrorRecordsOut,
    JobFailureDetails,
)
from resume_agent.services.errors import (
    dismiss_all,
    list_error_records,
    set_error_status,
)
from resume_agent.services.pagination import paginate
from resume_agent.tracking.tables import ErrorRecord

router = APIRouter()
ErrorStatus = Literal["open", "dismissed", "resolved"]
MAX_PAGE_SIZE = 200


def _job_details(record: ErrorRecord) -> JobFailureDetails | None:
    """Project stored JSON into the typed schema.

    Persisted JSON written by an older build is untrusted input at a read
    boundary: a shape mismatch must degrade to None, never a 500.
    """
    if record.kind != "job" or not record.details_json:
        return None
    try:
        return JobFailureDetails.model_validate(record.details_json)
    except ValidationError:
        return None


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
        job_details=_job_details(record),
    )


@router.get("/errors", response_model=ErrorRecordsOut)
def list_errors(
    status: ErrorStatus = Query("open"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE, alias="pageSize"),
    session: Session = Depends(get_session),
):
    records = list_error_records(session, status)
    window = paginate(records, page=page, page_size=page_size)
    return ErrorRecordsOut(
        records=[_row(record) for record in window.data],
        pagination=Pagination(
            page=window.page,
            page_size=window.page_size,
            total_items=window.total_items,
            total_pages=window.total_pages,
        ),
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
