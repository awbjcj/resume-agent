"""Funnel edges and median stage gaps for the recorded application timeline.

Median resists a single long-stalled application. Every cycle value carries its
sample size so the UI can apply one honest small-sample policy.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

from sqlmodel import Session, col, select

from resume_agent.tracking.event_vocab import FUNNEL_KINDS
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


@dataclass(frozen=True)
class FlowEdge:
    source: str
    target: str
    count: int


@dataclass(frozen=True)
class StageCycleTime:
    from_kind: str
    to_kind: str
    median_days: float
    sample_size: int


def _sort_moment(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("dated funnel event is missing occurred_at")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _sequences(session: Session) -> list[tuple[Application, list[ApplicationEvent]]]:
    applications = session.exec(
        select(Application)
        .join(Job, col(Application.job_id) == Job.id)
        .where(col(Job.archived_at).is_(None))
    ).all()
    application_ids = [
        application.id for application in applications if application.id is not None
    ]
    grouped: dict[int, list[ApplicationEvent]] = defaultdict(list)
    if application_ids:
        events = session.exec(
            select(ApplicationEvent).where(
                col(ApplicationEvent.application_id).in_(application_ids),
                col(ApplicationEvent.kind).in_(FUNNEL_KINDS),
                col(ApplicationEvent.occurred_at).is_not(None),
            )
        ).all()
        for event in events:
            grouped[event.application_id].append(event)
    for events in grouped.values():
        events.sort(
            key=lambda event: (
                _sort_moment(event.occurred_at),
                _sort_moment(event.created_at),
                event.id or 0,
            )
        )
    return [
        (application, grouped.get(application.id or -1, []))
        for application in applications
    ]


def _milestones(events: list[ApplicationEvent]) -> list[ApplicationEvent]:
    """Keep the first chronological visit to each strictly forward stage.

    Real histories can repeat rounds or record an earlier canonical stage
    later. Treating each adjacent raw pair independently splits one candidate
    into disconnected paths. A monotonic projection gives flows, exits, and
    cycle times the same coherent source history.
    """
    stage_index = {kind: index for index, kind in enumerate(FUNNEL_KINDS)}
    projected: list[ApplicationEvent] = []
    furthest = -1
    for event in events:
        current = stage_index[event.kind]
        if current > furthest:
            projected.append(event)
            furthest = current
    return projected


def stage_flows(session: Session) -> list[FlowEdge]:
    counts: Counter[tuple[str, str]] = Counter()
    for application, events in _sequences(session):
        milestones = _milestones(events)
        for previous, current in zip(milestones, milestones[1:], strict=False):
            counts[(previous.kind, current.kind)] += 1
        if not milestones:
            continue
        exit_kind: str | None = None
        if application.status == "rejected":
            exit_kind = "rejected"
        elif application.status == "closed":
            exit_kind = "withdrawn"
        elif events[-1].result == "no_response":
            exit_kind = "no_response"
        if exit_kind:
            counts[(milestones[-1].kind, exit_kind)] += 1
    return [
        FlowEdge(source=source, target=target, count=count)
        for (source, target), count in sorted(counts.items())
    ]


def stage_cycle_times(session: Session) -> list[StageCycleTime]:
    gaps: dict[tuple[str, str], list[float]] = defaultdict(list)
    for _, events in _sequences(session):
        milestones = _milestones(events)
        for previous, current in zip(milestones, milestones[1:], strict=False):
            if previous.occurred_at is None or current.occurred_at is None:
                continue
            days = max(
                0.0,
                (current.occurred_at - previous.occurred_at).total_seconds() / 86_400,
            )
            gaps[(previous.kind, current.kind)].append(days)
    return [
        StageCycleTime(
            from_kind=source,
            to_kind=target,
            median_days=median(values),
            sample_size=len(values),
        )
        for (source, target), values in sorted(gaps.items())
    ]
