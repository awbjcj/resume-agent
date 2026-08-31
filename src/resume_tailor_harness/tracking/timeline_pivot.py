"""Canonical application-timeline dataset for the grid and both CSV exports.

Every presentation projects this batched dataset so the readable grid, wide
export, and lossless event export cannot silently disagree.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

from sqlmodel import Session, col, select

from resume_tailor_harness.tracking.tables import Application, ApplicationEvent, Job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PivotCell:
    occurred_at: datetime | None
    all_day: bool
    result: str
    modality: str | None
    platform: str | None
    platform_other: str | None
    interviewers: str | None
    notes: str | None


@dataclass(frozen=True)
class PivotRow:
    job_id: int
    company: str | None
    title: str | None
    status: str
    source: str
    fit_score: int | None
    cells: dict[str, PivotCell]
    custom_count: int
    total_comp: int | None
    comp_currency: str | None
    offer_deadline: datetime | None
    events: tuple[ApplicationEvent, ...] = field(repr=False)


@dataclass
class PivotTable:
    rows: list[PivotRow]
    technical_round_columns: int
    overflow_by_job: dict[int, int]


def _sort_moment(value: datetime | None) -> datetime:
    if value is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _cell(event: ApplicationEvent) -> PivotCell:
    return PivotCell(
        occurred_at=_utc(event.occurred_at),
        all_day=event.all_day,
        result=event.result,
        modality=event.modality,
        platform=event.platform,
        platform_other=event.platform_other,
        interviewers=event.interviewers,
        notes=event.notes,
    )


def _comp_total(event: ApplicationEvent) -> int | None:
    parts = (
        event.comp_base,
        event.comp_bonus,
        event.comp_equity_annual,
        event.comp_signing,
    )
    return (
        sum(value for value in parts if value is not None)
        if any(value is not None for value in parts)
        else None
    )


def build_pivot(
    session: Session,
    *,
    max_technical_rounds: int | None = 6,
    job_ids: Collection[int] | None = None,
) -> PivotTable:
    query = (
        select(Application, Job)
        .join(Job, col(Application.job_id) == Job.id)
        .where(col(Job.archived_at).is_(None))
    )
    if job_ids is not None:
        scoped_ids = set(job_ids)
        if not scoped_ids:
            return PivotTable(rows=[], technical_round_columns=0, overflow_by_job={})
        query = query.where(col(Job.id).in_(scoped_ids))
    application_rows = session.exec(query).all()
    application_ids = [
        application.id
        for application, _ in application_rows
        if application.id is not None
    ]
    events_by_application: dict[int, list[ApplicationEvent]] = defaultdict(list)
    if application_ids:
        events = session.exec(
            select(ApplicationEvent).where(
                col(ApplicationEvent.application_id).in_(application_ids)
            )
        ).all()
        for event in events:
            events_by_application[event.application_id].append(event)

    rows: list[tuple[datetime | None, PivotRow]] = []
    overflow_by_job: dict[int, int] = {}
    maximum_round = 0
    for application, job in application_rows:
        if job.id is None:
            continue
        events = sorted(
            events_by_application.get(application.id or -1, []),
            key=lambda event: (
                _sort_moment(event.occurred_at),
                _sort_moment(event.created_at),
                event.id or 0,
            ),
        )
        cells: dict[str, PivotCell] = {}
        custom_count = 0
        deadline: datetime | None = None
        offers: list[ApplicationEvent] = []
        overflow = 0
        for event in events:
            if event.kind == "custom":
                custom_count += 1
                continue
            if event.kind == "technical_round":
                maximum_round = max(maximum_round, event.sequence)
                if (
                    max_technical_rounds is not None
                    and event.sequence > max_technical_rounds
                ):
                    overflow += 1
                    continue
                key = f"technical_round_{event.sequence}"
            else:
                key = event.kind
            if event.kind == "technical_round" and key in cells:
                overflow += 1
                logger.warning(
                    "Duplicate pivot cell job_id=%s kind=%s sequence=%s",
                    job.id,
                    event.kind,
                    event.sequence,
                )
            cells[key] = _cell(event)
            if event.kind == "offer_received":
                offers.append(event)
            elif event.kind == "offer_deadline":
                deadline = _utc(event.occurred_at)
        if overflow:
            overflow_by_job[job.id] = overflow
        latest_offer = offers[-1] if offers else None
        recent = max(
            (event.occurred_at for event in events if event.occurred_at), default=None
        )
        rows.append(
            (
                recent,
                PivotRow(
                    job_id=job.id,
                    company=job.company,
                    title=job.title,
                    status=application.status,
                    source=job.source,
                    fit_score=job.fit_score,
                    cells=cells,
                    custom_count=custom_count,
                    total_comp=_comp_total(latest_offer) if latest_offer else None,
                    comp_currency=latest_offer.comp_currency if latest_offer else None,
                    offer_deadline=deadline,
                    events=tuple(events),
                ),
            )
        )

    rows.sort(
        key=lambda item: (
            item[0] is not None,
            _sort_moment(item[0])
            if item[0] is not None
            else datetime.min.replace(tzinfo=timezone.utc),
            item[1].job_id,
        ),
        reverse=True,
    )
    shown_rounds = maximum_round
    if max_technical_rounds is not None:
        shown_rounds = min(shown_rounds, max_technical_rounds)
    return PivotTable(
        rows=[row for _, row in rows],
        technical_round_columns=shown_rounds,
        overflow_by_job=overflow_by_job,
    )
