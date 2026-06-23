"""Single-job endpoints: detail (this task), mutations (Task 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.jobs import (
    ApplicationOut,
    ApplicationUpsert,
    JobDetail,
    JobPatch,
    ResumeVersionOut,
    SkillTagOut,
)
from resume_agent.api.schemas.runs import AddJobTextRequest
from resume_agent.services import board
from resume_agent.services.discovery import add_job_from_text
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    has_progress,
    resume_versions_for_job,
)
from resume_agent.tracking.tables import ApplicationStatus, JobStatus

router = APIRouter()


def _job_detail(session: Session, job_id: int) -> JobDetail:
    job = get_job(session, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    assert job.id is not None
    application = application_for_job(session, job_id)
    versions = resume_versions_for_job(session, job_id)
    facets = board.job_detail_facets(session, job_id)
    skills = [SkillTagOut.model_validate(t) for t in facets.skills] if facets else []
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
        skills=skills,
        sponsorship_signal=facets.sponsorship_signal if facets else None,
        salary_min=facets.salary_min if facets else None,
        salary_max=facets.salary_max if facets else None,
        salary_currency=facets.salary_currency if facets else None,
        remote_policy=facets.remote_policy if facets else None,
        seniority=facets.seniority if facets else None,
        employment_type=facets.employment_type if facets else None,
        industry=facets.industry if facets else None,
        company_size=facets.company_size if facets else None,
        sic_major=facets.sic_major if facets else None,
        sic_label=facets.sic_label if facets else None,
        sic_division=facets.sic_division if facets else None,
        location_country=facets.location_country if facets else None,
        location_region=facets.location_region if facets else None,
        location_city=facets.location_city if facets else None,
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(job_id: int, session: Session = Depends(get_session)):
    return _job_detail(session, job_id)


@router.patch("/jobs/{job_id}", response_model=JobDetail)
def patch_job(job_id: int, patch: JobPatch, session: Session = Depends(get_session)):
    if patch.status is not None:
        valid = {s.value for s in JobStatus}
        if patch.status not in valid:
            raise ApiException(422, "VALIDATION_ERROR", f"Unknown status '{patch.status}'")
        if board.set_stage(session, job_id, patch.status) is None:
            raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if patch.archived is not None:
        if board.set_archived(session, job_id, patch.archived) is None:
            raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return _job_detail(session, job_id)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job_endpoint(job_id: int, session: Session = Depends(get_session)) -> Response:
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if not board.delete(session, job_id):
        raise ApiException(409, "CONFLICT", "Job has progress and cannot be deleted")
    return Response(status_code=204)


@router.put("/jobs/{job_id}/application", response_model=ApplicationOut)
def upsert_application(
    job_id: int, body: ApplicationUpsert, session: Session = Depends(get_session)
):
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    valid = {s.value for s in ApplicationStatus}
    if body.status not in valid:
        raise ApiException(422, "VALIDATION_ERROR", f"Unknown application status '{body.status}'")
    app_row = board.upsert_application(session, job_id, status=body.status, notes=body.notes)
    return ApplicationOut.model_validate(app_row)


@router.post("/jobs", response_model=JobDetail, status_code=201)
def create_manual_job(body: AddJobTextRequest, session: Session = Depends(get_session)):
    job = add_job_from_text(
        session, jd_text=body.jd_text, url=body.url,
        company=body.company, title=body.title, location=body.location,
    )
    if job is None:
        raise ApiException(409, "CONFLICT", "Duplicate job (same URL or JD already present)")
    assert job.id is not None
    return _job_detail(session, job.id)
