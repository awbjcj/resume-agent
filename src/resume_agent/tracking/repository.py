from typing import Any, cast

from sqlalchemy import func
from sqlmodel import Session, select

from resume_agent.tracking.tables import (
    Application,
    ApplicationStatus,
    CoverLetter,
    Job,
    JobStatus,
    ResumeVersion,
    utcnow,
)


def _stamp_submitted_at(application: Application) -> None:
    if application.status == ApplicationStatus.submitted.value and application.submitted_at is None:
        application.submitted_at = utcnow()


def save_job(session: Session, job: Job) -> Job:
    """Insert or update a job (SQLModel ``add`` handles both)."""
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def jobs_by_status(session: Session, status: str) -> list[Job]:
    archived_col = cast(Any, Job.archived_at)
    return list(
        session.exec(
            select(Job).where(Job.status == status, archived_col.is_(None))
        ).all()
    )


def find_existing(
    session: Session, url: str | None, jd_text: str, dedup_key: str | None = None
) -> Job | None:
    """Return a matching job for dedupe: by URL, else identical JD text, else dedup_key."""
    if url:
        by_url = session.exec(select(Job).where(Job.url == url)).first()
        if by_url is not None:
            return by_url
    if jd_text:
        by_jd = session.exec(select(Job).where(Job.jd_text == jd_text)).first()
        if by_jd is not None:
            return by_jd
    if dedup_key:
        return session.exec(select(Job).where(Job.dedup_key == dedup_key)).first()
    return None


def status_counts(session: Session) -> dict[str, int]:
    archived_col = cast(Any, Job.archived_at)
    rows = session.exec(
        select(Job.status, func.count())
        .where(archived_col.is_(None))
        .group_by(Job.status)
    ).all()
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


def get_resume_version(session: Session, version_id: int) -> ResumeVersion | None:
    return session.get(ResumeVersion, version_id)


def save_application(session: Session, application: Application) -> Application:
    _stamp_submitted_at(application)
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def get_application(session: Session, application_id: int) -> Application | None:
    return session.get(Application, application_id)


def application_for_job(session: Session, job_id: int) -> Application | None:
    return session.exec(select(Application).where(Application.job_id == job_id)).first()


def applications_by_status(session: Session, status: str) -> list[Application]:
    return list(session.exec(select(Application).where(Application.status == status)).all())


def update_application_status(
    session: Session, application_id: int, status: str, notes: str | None = None
) -> Application | None:
    application = session.get(Application, application_id)
    if application is None:
        return None
    application.status = status
    _stamp_submitted_at(application)
    if notes is not None:
        application.notes = notes
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def latest_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    round_col = cast(Any, ResumeVersion.round)
    id_col = cast(Any, ResumeVersion.id)
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id)
        .order_by(round_col.desc(), id_col.desc())
    ).first()


def latest_rendered_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    pdf_path_col = cast(Any, ResumeVersion.pdf_path)
    round_col = cast(Any, ResumeVersion.round)
    id_col = cast(Any, ResumeVersion.id)
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id, pdf_path_col.is_not(None))
        .order_by(round_col.desc(), id_col.desc())
    ).first()


def save_cover_letter(session: Session, cover_letter: CoverLetter) -> CoverLetter:
    session.add(cover_letter)
    session.commit()
    session.refresh(cover_letter)
    return cover_letter


def get_cover_letter(session: Session, cover_letter_id: int) -> CoverLetter | None:
    return session.get(CoverLetter, cover_letter_id)


_PROGRESS_STATUSES = {
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
}


def archive_job(session: Session, job_id: int) -> Job | None:
    """Soft-archive a job (reversible). Status is left untouched."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    job.archived_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def restore_job(session: Session, job_id: int) -> Job | None:
    """Un-archive a job, restoring it to its exact prior stage."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    job.archived_at = None
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def delete_job(session: Session, job_id: int) -> bool:
    """Hard-delete a zero-progress job and its children in one transaction.

    Returns False (and changes nothing) if the job has user progress or is
    already gone. The progress check is the single irreversible-path guard.
    """
    if has_progress(session, job_id):
        return False
    job = session.get(Job, job_id)
    if job is None:
        return False
    # Dependency order: CoverLetter/Application can reference ResumeVersion.
    for model in (CoverLetter, Application, ResumeVersion):
        for child in session.exec(select(model).where(model.job_id == job_id)).all():
            session.delete(child)
    session.delete(job)
    session.commit()
    return True


def has_progress(session: Session, job_id: int) -> bool:
    """True if a job has user investment that must never be destroyed."""
    job = session.get(Job, job_id)
    if job is None:
        return False
    if job.status in _PROGRESS_STATUSES:
        return True
    for model in (Application, ResumeVersion, CoverLetter):
        if session.exec(select(model).where(model.job_id == job_id)).first() is not None:
            return True
    return False
