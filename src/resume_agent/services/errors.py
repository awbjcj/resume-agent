"""Durable error records with deduplication and user-managed terminal states."""

from __future__ import annotations

from datetime import timedelta
from threading import RLock
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from resume_agent.tracking.tables import ErrorRecord, utcnow

RETENTION_DAYS = 30
_KINDS = {"run", "source"}
_TERMINAL = {"dismissed", "resolved"}
_WRITE_LOCK = RLock()


def record_error(
    session: Session,
    *,
    kind: str,
    source_label: str,
    message: str,
    run_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> ErrorRecord:
    if kind not in _KINDS:
        raise ValueError(f"invalid error kind: {kind}")
    if not source_label:
        raise ValueError("error source label is required")

    with _WRITE_LOCK:
        existing = session.exec(
            select(ErrorRecord).where(
                ErrorRecord.kind == kind,
                ErrorRecord.source_label == source_label,
                ErrorRecord.status == "open",
            )
        ).first()
        now = utcnow()
        if existing is not None:
            existing.count += 1
            existing.message = message
            existing.run_id = run_id or existing.run_id
            existing.details_json = details
            existing.last_seen_at = now
            existing.updated_at = now
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        record = ErrorRecord(
            kind=kind,
            source_label=source_label,
            message=message,
            run_id=run_id,
            details_json=details,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def record_source_failures(
    session: Session,
    failures: dict[str, dict[str, str]],
    *,
    run_id: str | None = None,
) -> int:
    written = 0
    for connector, unit_failures in failures.items():
        for unit, reason in unit_failures.items():
            record_error(
                session,
                kind="source",
                source_label=f"{connector}:{unit}",
                message=reason,
                run_id=run_id,
            )
            written += 1
    return written


def _prune(session: Session) -> None:
    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
    stale = session.exec(
        select(ErrorRecord).where(
            col(ErrorRecord.status).in_(_TERMINAL),
            ErrorRecord.updated_at < cutoff,
        )
    ).all()
    for record in stale:
        session.delete(record)
    if stale:
        session.commit()


def list_error_records(
    session: Session, status: str | None = "open"
) -> list[ErrorRecord]:
    _prune(session)
    query = select(ErrorRecord).order_by(col(ErrorRecord.last_seen_at).desc())
    if status is not None:
        query = query.where(ErrorRecord.status == status)
    return list(session.exec(query).all())


def set_error_status(session: Session, record_id: int, status: str) -> ErrorRecord:
    if status not in _TERMINAL:
        raise ValueError(f"invalid status: {status}")
    record = session.get(ErrorRecord, record_id)
    if record is None:
        raise ValueError(f"unknown error record: {record_id}")
    if record.status != "open":
        raise ValueError("error record is not open")
    record.status = status
    record.updated_at = utcnow()
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def dismiss_all(session: Session) -> int:
    rows = session.exec(
        select(ErrorRecord).where(ErrorRecord.status == "open")
    ).all()
    now = utcnow()
    for record in rows:
        record.status = "dismissed"
        record.updated_at = now
        session.add(record)
    if rows:
        session.commit()
    return len(rows)


def count_open(session: Session) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(ErrorRecord).where(
                ErrorRecord.status == "open"
            )
        ).one()
    )
