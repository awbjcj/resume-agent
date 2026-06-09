from sqlalchemy import func
from sqlmodel import Session, select

from resume_agent.tracking.tables import Job, ResumeVersion


def save_job(session: Session, job: Job) -> Job:
    """Insert or update a job (SQLModel ``add`` handles both)."""
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def jobs_by_status(session: Session, status: str) -> list[Job]:
    return list(session.exec(select(Job).where(Job.status == status)).all())


def find_existing(session: Session, url: str | None, jd_text: str) -> Job | None:
    """Return a matching job by URL (if given) else by identical JD text, for dedupe."""
    if url:
        by_url = session.exec(select(Job).where(Job.url == url)).first()
        if by_url is not None:
            return by_url
    return session.exec(select(Job).where(Job.jd_text == jd_text)).first()


def status_counts(session: Session) -> dict[str, int]:
    rows = session.exec(select(Job.status, func.count()).group_by(Job.status)).all()
    return {status: count for status, count in rows}


def get_job(session: Session, job_id: int) -> Job | None:
    return session.get(Job, job_id)


def save_resume_version(session: Session, version: ResumeVersion) -> ResumeVersion:
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def resume_versions_for_job(session: Session, job_id: int) -> list[ResumeVersion]:
    return list(session.exec(select(ResumeVersion).where(ResumeVersion.job_id == job_id)).all())
