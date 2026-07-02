"""Read-only dashboard projection: one query pass, no business logic."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, col, func, select

from resume_agent.tracking.queries import _TRIAGE_STATUSES
from resume_agent.tracking.tables import Application, Job, JobStatus

# Pipeline stages that are literally "waiting on the user", keyed by queue name.
# triage mirrors _TRIAGE_STATUSES (the same set the Triage page query gates on),
# not just "filtered", so this queue count stays consistent with that view.
QUEUE_STATUSES: dict[str, tuple[str, ...]] = {
    "triage": _TRIAGE_STATUSES,
    "approve": (JobStatus.shortlisted.value,),
    "tailor": (JobStatus.approved.value,),
    "apply": (JobStatus.rendered.value,),
}


@dataclass(frozen=True)
class DashboardSummary:
    status_counts: dict[str, int] = field(default_factory=dict)
    queues: dict[str, int] = field(default_factory=dict)
    applied: int = 0


def summarize_dashboard(session: Session) -> DashboardSummary:
    rows = session.exec(
        select(Job.status, func.count())
        .where(Job.archived_at == None)  # noqa: E711 — SQL IS NULL
        .group_by(Job.status)
    ).all()
    counts = {status.value: 0 for status in JobStatus}
    for status, count in rows:
        counts[status] = count
    queues = {
        name: sum(counts.get(s, 0) for s in statuses)
        for name, statuses in QUEUE_STATUSES.items()
    }
    applied = session.exec(
        select(func.count())
        .select_from(Application)
        .join(Job, col(Application.job_id) == Job.id)
        .where(Application.status != "ready", Job.archived_at == None)  # noqa: E711
    ).one()
    return DashboardSummary(status_counts=counts, queues=queues, applied=applied)
