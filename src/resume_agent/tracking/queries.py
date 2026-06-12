from dataclasses import dataclass
from typing import Any, cast

from sqlmodel import Session, select

from resume_agent.tracking.repository import (
    application_for_job,
    latest_rendered_resume_version,
    latest_resume_version,
)
from resume_agent.tracking.tables import Application, Job, JobStatus


def _require_job_id(job: Job) -> int:
    if job.id is None:
        raise ValueError("Encountered a job row without a persisted id")
    return job.id


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
    fit_score_col = cast(Any, Job.fit_score)
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value)
        .order_by(fit_score_col.desc().nullslast())
    ).all()
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        rows.append(
            ShortlistRow(
                job_id=job_id,
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
    status_col = cast(Any, Job.status)
    company_col = cast(Any, Job.company)
    title_col = cast(Any, Job.title)
    jobs = session.exec(select(Job).order_by(status_col, company_col, title_col)).all()
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        version = latest_resume_version(session, job_id)
        rendered = latest_rendered_resume_version(session, job_id)
        application = application_for_job(session, job_id)
        rows.append(
            PipelineRow(
                job_id=job_id,
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


def application_job_pairs(session: Session) -> list[tuple[Application, Job]]:
    """Every application paired with its job (one query, no N+1 per-row fetch)."""
    statement = select(Application, Job).join(Job, Application.job_id == Job.id)
    return [(app, job) for app, job in session.exec(statement).all()]
