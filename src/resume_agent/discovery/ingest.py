from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from sqlalchemy import func, select
from sqlmodel import Session, col

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.merge import (
    IncomingJob,
    Insert,
    MergeAction,
    Rebase,
    RefreshText,
    RefreshCompany,
    Skip,
    UpgradeUrlOnly,
    decide,
)
from resume_agent.tracking.repository import (
    company_rename_collides,
    find_existing,
    has_progress,
)
from resume_agent.tracking.tables import Job, JobStatus


class IngestOutcome(str, Enum):
    inserted = "inserted"
    upgraded = "upgraded"
    skipped = "skipped"
    quota_skipped = "quota_skipped"


@dataclass(frozen=True)
class IngestCounts:
    added: dict[str, int]
    upgraded: dict[str, int]
    skipped: dict[str, int]
    quota_skipped: dict[str, int]
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
    allow_insert: bool = True,
    stale_company: str | None = None,
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
        stale_company=stale_company,
    )
    existing = find_existing(
        session,
        incoming.url,
        incoming.jd_text,
        incoming.dedup_key,
        incoming.content_fingerprint,
        incoming.location,
    )
    action = decide(existing, incoming)
    if (
        isinstance(action, RefreshText)
        and existing is not None
        and existing.id is not None
        and has_progress(session, existing.id)
    ):
        # A materially richer page invalidates extraction and scoring, but a
        # user-invested row must not be silently rewritten underneath an
        # application or authored artifact. Explicit Redo remains available
        # for those rows because it re-pulls and re-extracts as one operation.
        action = Skip()
    refreshed_key: str | None = None
    changes_identity = False
    if isinstance(action, RefreshCompany):
        refreshed_key = action.dedup_key
        changes_identity = True
    elif isinstance(action, RefreshText) and "dedup_key" in action.updates:
        refreshed_key = action.updates["dedup_key"]
        changes_identity = True
    if (
        changes_identity
        and existing is not None
        and refreshed_key != existing.dedup_key
        and company_rename_collides(session, existing=existing, dedup_key=refreshed_key)
    ):
        action = Skip()
    if isinstance(action, Insert) and not allow_insert:
        return None, IngestOutcome.quota_skipped
    return _apply(session, existing, incoming, action, commit)


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
        if isinstance(action, RefreshText) and existing.status != JobStatus.raw.value:
            # Text-derived fields must never describe the previous, truncated
            # posting. Reset unprogressed rows so refresh/discovery extracts
            # salary, employment type, and other facts from the richer copy.
            existing.status = JobStatus.raw.value
            existing.criteria_json = None
            existing.analysis_meta_json = None
            existing.fit_score = None
            existing.fit_rationale = None
            existing.reject_reason = None
            existing.reject_category = None
            existing.industry_pending = False
        for field, value in action.updates.items():
            setattr(existing, field, value)
    elif isinstance(action, RefreshCompany):
        existing.company = action.company
        existing.dedup_key = action.dedup_key
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


def ingest_jobs_with_outcomes(
    session: Session,
    raw_jobs: Iterable[RawJob],
    *,
    max_active_jobs: int | None = None,
) -> IngestCounts:
    """Insert/upgrade RawJobs and return separate insert/upgrade counts per incoming source."""
    added: Counter[str] = Counter()
    upgraded: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    quota_skipped: Counter[str] = Counter()
    changed_raw_job_ids: list[int] = []
    seen_changed_raw: set[int] = set()
    remaining: int | None = None
    if max_active_jobs is not None and max_active_jobs > 0:
        active = session.execute(
            select(func.count()).select_from(Job).where(col(Job.archived_at).is_(None))
        ).scalar_one()
        remaining = max(max_active_jobs - int(active), 0)
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
            stale_company=raw.stale_company,
            commit=False,
            allow_insert=remaining is None or remaining > 0,
        )
        if outcome is IngestOutcome.inserted:
            if remaining is not None:
                remaining -= 1
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
        elif outcome is IngestOutcome.quota_skipped:
            quota_skipped[raw.source] += 1
    session.commit()
    return IngestCounts(
        added=dict(added),
        upgraded=dict(upgraded),
        skipped=dict(skipped),
        quota_skipped=dict(quota_skipped),
        changed_raw_job_ids=changed_raw_job_ids,
    )


def ingest_jobs(
    session: Session,
    raw_jobs: Iterable[RawJob],
    *,
    max_active_jobs: int | None = None,
) -> dict[str, int]:
    """Backward-compatible insert counts; upgrades are intentionally not new adds."""
    return ingest_jobs_with_outcomes(
        session, raw_jobs, max_active_jobs=max_active_jobs
    ).added
