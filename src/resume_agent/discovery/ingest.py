from collections import Counter
from datetime import datetime
from typing import Iterable

from sqlmodel import Session

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.tracking.repository import find_existing, save_job
from resume_agent.tracking.dedup import compute_dedup_key
from resume_agent.tracking.tables import Job, JobStatus


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


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
    """Normalize, dedupe, and insert a raw job. Returns None if a duplicate exists."""
    jd_text = jd_text.strip()
    url = _clean(url)
    company = _clean(company)
    title = _clean(title)
    dedup_key = compute_dedup_key(company, title)
    if find_existing(session, url, jd_text, dedup_key) is not None:
        return None
    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=_clean(location),
        posted_at=posted_at,
        dedup_key=dedup_key,
        status=JobStatus.raw.value,
    )
    return save_job(session, job)


def ingest_jobs(session: Session, raw_jobs: Iterable[RawJob]) -> dict[str, int]:
    """Insert RawJobs through the shared normalize/dedupe path."""
    added: Counter[str] = Counter()
    for raw in raw_jobs:
        if not raw.jd_text.strip():
            continue
        job = add_job(
            session,
            source=raw.source,
            jd_text=raw.jd_text,
            url=raw.url,
            company=raw.company,
            title=raw.title,
            location=raw.location,
            posted_at=raw.posted_at,
        )
        if job is not None:
            added[raw.source] += 1
    return dict(added)
