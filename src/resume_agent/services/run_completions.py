"""Durable terminal run history and read state."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, col, select

from resume_agent.tracking.tables import RunCompletion, utcnow

RUN_COMPLETION_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def record_run_completion(
    session: Session,
    *,
    run_id: str,
    kind: str,
    label: str,
    status: str,
    error: str | None,
    completed_at: datetime,
) -> RunCompletion:
    if status not in RUN_COMPLETION_STATUSES:
        raise ValueError(f"unsupported run completion status: {status}")
    existing = session.exec(
        select(RunCompletion).where(RunCompletion.run_id == run_id)
    ).first()
    if existing is not None:
        return existing
    row = RunCompletion(
        run_id=run_id,
        kind=kind,
        label=label,
        status=status,
        error=error,
        completed_at=completed_at,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_run_completions(
    session: Session, *, limit: int = 50, unread_only: bool = False
) -> list[RunCompletion]:
    query = select(RunCompletion).order_by(col(RunCompletion.completed_at).desc())
    if unread_only:
        query = query.where(RunCompletion.read_at.is_(None))
    return list(session.exec(query.limit(limit)).all())


def mark_run_completion_read(session: Session, completion_id: int) -> RunCompletion | None:
    row = session.get(RunCompletion, completion_id)
    if row is None:
        return None
    if row.read_at is None:
        row.read_at = utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def mark_all_run_completions_read(session: Session) -> int:
    rows = session.exec(
        select(RunCompletion).where(RunCompletion.read_at.is_(None))
    ).all()
    if not rows:
        return 0
    read_at = utcnow()
    for row in rows:
        row.read_at = read_at
        session.add(row)
    session.commit()
    return len(rows)
