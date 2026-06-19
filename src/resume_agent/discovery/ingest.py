from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from sqlmodel import Session

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.source_tier import source_rank
from resume_agent.tracking.dedup import compute_dedup_key
from resume_agent.tracking.repository import find_existing, save_job
from resume_agent.tracking.tables import Job, JobStatus


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class IngestOutcome(str, Enum):
    inserted = "inserted"
    upgraded = "upgraded"
    skipped = "skipped"


@dataclass(frozen=True)
class IngestCounts:
    added: dict[str, int]
    upgraded: dict[str, int]


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
) -> tuple[Job | None, IngestOutcome]:
    """Insert a new job, upgrade an existing one from a higher-tier source, or skip."""
    jd_text = jd_text.strip()
    url = _clean(url)
    company = _clean(company)
    title = _clean(title)
    incoming_location = _clean(location)
    dedup_key = compute_dedup_key(company, title)

    existing = find_existing(session, url, jd_text, dedup_key)
    if existing is not None:
        if source_rank(source) >= source_rank(existing.source):
            return None, IngestOutcome.skipped
        if existing.status != JobStatus.raw.value:
            if not url:
                return None, IngestOutcome.skipped
            existing.url = url
            existing.source = source
            return save_job(session, existing), IngestOutcome.upgraded

        # Higher-tier re-see while raw: re-base the posting text, but do not erase
        # existing optional fields when the incoming source omitted them.
        existing.source = source
        existing.jd_text = jd_text
        if url:
            existing.url = url
        if company is not None:
            existing.company = company
        if title is not None:
            existing.title = title
        if incoming_location is not None:
            existing.location = incoming_location
        if posted_at is not None:
            existing.posted_at = posted_at
        existing.dedup_key = compute_dedup_key(existing.company, existing.title)
        return save_job(session, existing), IngestOutcome.upgraded

    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=incoming_location,
        posted_at=posted_at,
        dedup_key=dedup_key,
        status=JobStatus.raw.value,
    )
    return save_job(session, job), IngestOutcome.inserted


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
    for raw in raw_jobs:
        if not raw.jd_text.strip():
            continue
        _job, outcome = save_or_upgrade(
            session,
            source=raw.source,
            jd_text=raw.jd_text,
            url=raw.url,
            company=raw.company,
            title=raw.title,
            location=raw.location,
            posted_at=raw.posted_at,
        )
        if outcome is IngestOutcome.inserted:
            added[raw.source] += 1
        elif outcome is IngestOutcome.upgraded:
            upgraded[raw.source] += 1
    return IngestCounts(added=dict(added), upgraded=dict(upgraded))


def ingest_jobs(session: Session, raw_jobs: Iterable[RawJob]) -> dict[str, int]:
    """Backward-compatible insert counts; upgrades are intentionally not new adds."""
    return ingest_jobs_with_outcomes(session, raw_jobs).added
