from dataclasses import dataclass

from sqlmodel import Session, select

from resume_agent.tracking.repository import (
    application_for_job,
    latest_rendered_resume_version,
    latest_resume_version,
)
from resume_agent.tracking.tables import Job, JobStatus


@dataclass
class ShortlistRow:
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None


@dataclass
class PipelineRow:
    job_id: int
    company: str | None
    title: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None


def shortlist_rows(session: Session) -> list[ShortlistRow]:
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value)
        .order_by(Job.fit_score.desc().nullslast())
    ).all()
    rows = []
    for job in jobs:
        criteria = job.criteria_json or {}
        rows.append(
            ShortlistRow(
                job_id=job.id,
                company=job.company,
                title=job.title,
                location=job.location,
                fit_score=job.fit_score,
                fit_rationale=job.fit_rationale,
                sponsorship_signal=criteria.get("sponsorship_signal"),
            )
        )
    return rows


def pipeline_rows(session: Session) -> list[PipelineRow]:
    jobs = session.exec(select(Job).order_by(Job.status, Job.company, Job.title)).all()
    rows = []
    for job in jobs:
        version = latest_resume_version(session, job.id)
        rendered = latest_rendered_resume_version(session, job.id)
        application = application_for_job(session, job.id)
        rows.append(
            PipelineRow(
                job_id=job.id,
                company=job.company,
                title=job.title,
                status=job.status,
                fit_score=job.fit_score,
                jd_text=job.jd_text,
                critique_json=version.critique_json if version else None,
                pdf_path=rendered.pdf_path if rendered else None,
                application_status=application.status if application else None,
            )
        )
    return rows
