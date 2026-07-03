from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from sqlmodel import Session

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.merge import (
    IncomingJob,
    Insert,
    MergeAction,
    Rebase,
    RefreshText,
    Skip,
    UpgradeUrlOnly,
    decide,
)
from resume_agent.tracking.repository import find_existing
from resume_agent.tracking.tables import Job, JobStatus


class IngestOutcome(str, Enum):
    inserted = "inserted"
    upgraded = "upgraded"
    skipped = "skipped"


@dataclass(frozen=True)
class IngestCounts:
    added: dict[str, int]
    upgraded: dict[str, int]
    skipped: dict[str, int]
    changed_raw_job_ids: list[int]


def _persist(session: Session, job: Job, commit: bool) -> Job:
    session.add(job)
    if commit:
        session.commit()
        session.refresh(job)
    else:
        # flush() assigns the id and makes the row visible to find_existing
        # for later items in the same batch, without ending the transaction.
        session.flush()
    return job


def save_or_upgrade(
    session: Session,
    *,
    source: str,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    posted_at: datetime | None = None,
    commit: bool = True,
) -> tuple[Job | None, IngestOutcome]:
    """Insert a new job, upgrade an existing one from a higher-tier source, or skip."""
    incoming = IncomingJob.clean(
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=location,
        posted_at=posted_at,
    )
    existing = find_existing(
        session,
        incoming.url,
        incoming.jd_text,
        incoming.dedup_key,
        incoming.content_fingerprint,
    )
    return _apply(session, existing, incoming, decide(existing, incoming), commit)


def _apply(
    session: Session,
    existing: Job | None,
    incoming: IncomingJob,
    action: MergeAction,
    commit: bool,
) -> tuple[Job | None, IngestOutcome]:
    """Carry out the pure merge decision against the database."""
    if isinstance(action, Skip):
        return None, IngestOutcome.skipped
    if isinstance(action, Insert):
        job = Job(
            source=incoming.source,
            jd_text=incoming.jd_text,
            url=incoming.url,
            company=incoming.company,
            title=incoming.title,
            location=incoming.location,
            posted_at=incoming.posted_at,
            dedup_key=incoming.dedup_key,
            content_fingerprint=incoming.content_fingerprint,
            status=JobStatus.raw.value,
        )
        return _persist(session, job, commit), IngestOutcome.inserted
    # The remaining actions mutate the matched row in place.
    assert existing is not None
    if isinstance(action, UpgradeUrlOnly):
        existing.url = action.url
        existing.source = action.source
    elif isinstance(action, (Rebase, RefreshText)):
        for field, value in action.updates.items():
            setattr(existing, field, value)
    return _persist(session, existing, commit), IngestOutcome.upgraded


def add_job(
    session: Session,
    *,
    source: str,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    posted_at: datetime | None = None,
) -> Job | None:
    """Normalize, dedupe, and insert/upgrade a raw job. Returns None when skipped."""
    job, _ = save_or_upgrade(
        session,
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=location,
        posted_at=posted_at,
    )
    return job


def ingest_jobs_with_outcomes(session: Session, raw_jobs: Iterable[RawJob]) -> IngestCounts:
    """Insert/upgrade RawJobs and return separate insert/upgrade counts per incoming source."""
    added: Counter[str] = Counter()
    upgraded: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    changed_raw_job_ids: list[int] = []
    seen_changed_raw: set[int] = set()
    for raw in raw_jobs:
        if not raw.jd_text.strip():
            continue
        job, outcome = save_or_upgrade(
            session,
            source=raw.source,
            jd_text=raw.jd_text,
            url=raw.url,
            company=raw.company,
            title=raw.title,
            location=raw.location,
            posted_at=raw.posted_at,
            commit=False,
        )
        if outcome is IngestOutcome.inserted:
            added[raw.source] += 1
            if job is not None and job.id is not None:
                seen_changed_raw.add(job.id)
                changed_raw_job_ids.append(job.id)
        elif outcome is IngestOutcome.upgraded:
            upgraded[raw.source] += 1
            if (
                job is not None
                and job.id is not None
                and job.status == JobStatus.raw.value
                and job.id not in seen_changed_raw
            ):
                seen_changed_raw.add(job.id)
                changed_raw_job_ids.append(job.id)
        elif outcome is IngestOutcome.skipped:
            skipped[raw.source] += 1
    session.commit()
    return IngestCounts(
        added=dict(added),
        upgraded=dict(upgraded),
        skipped=dict(skipped),
        changed_raw_job_ids=changed_raw_job_ids,
    )


def ingest_jobs(session: Session, raw_jobs: Iterable[RawJob]) -> dict[str, int]:
    """Backward-compatible insert counts; upgrades are intentionally not new adds."""
    return ingest_jobs_with_outcomes(session, raw_jobs).added
