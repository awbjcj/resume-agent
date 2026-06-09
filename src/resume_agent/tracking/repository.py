from sqlalchemy import func
from sqlmodel import Session, select

from resume_agent.tracking.tables import Application, Job, ResumeVersion


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


def get_resume_version(session: Session, version_id: int) -> ResumeVersion | None:
    return session.get(ResumeVersion, version_id)


def save_application(session: Session, application: Application) -> Application:
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
    if notes is not None:
        application.notes = notes
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def latest_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id)
        .order_by(ResumeVersion.round.desc())
    ).first()


def latest_rendered_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id, ResumeVersion.pdf_path.is_not(None))
        .order_by(ResumeVersion.round.desc())
    ).first()
