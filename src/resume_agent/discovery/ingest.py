from sqlmodel import Session

from resume_agent.tracking.repository import find_existing, save_job
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
) -> Job | None:
    """Normalize, dedupe, and insert a raw job. Returns None if a duplicate exists."""
    jd_text = jd_text.strip()
    url = _clean(url)
    if find_existing(session, url, jd_text) is not None:
        return None
    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=_clean(company),
        title=_clean(title),
        location=_clean(location),
        status=JobStatus.raw.value,
    )
    return save_job(session, job)
