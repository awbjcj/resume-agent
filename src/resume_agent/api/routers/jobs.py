"""Single-job endpoints: detail (this task), mutations (Task 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.jobs import (
    ApplicationOut,
    JobDetail,
    ResumeVersionOut,
)
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    has_progress,
    resume_versions_for_job,
)

router = APIRouter()


def _job_detail(session: Session, job_id: int) -> JobDetail:
    job = get_job(session, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    application = application_for_job(session, job_id)
    versions = resume_versions_for_job(session, job_id)
    return JobDetail(
        id=job.id,
        source=job.source,
        url=job.url,
        company=job.company,
        title=job.title,
        location=job.location,
        jd_text=job.jd_text,
        status=job.status,
        fit_score=job.fit_score,
        fit_rationale=job.fit_rationale,
        criteria_json=job.criteria_json,
        posted_at=job.posted_at,
        archived_at=job.archived_at,
        created_at=job.created_at,
        has_progress=has_progress(session, job_id),
        application=ApplicationOut.model_validate(application) if application else None,
        resume_versions=[ResumeVersionOut.model_validate(v) for v in versions],
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(job_id: int, session: Session = Depends(get_session)):
    return _job_detail(session, job_id)
