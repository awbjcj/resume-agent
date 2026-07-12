"""Single-job endpoints: detail (this task), mutations (Task 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.bulk import BulkRequest, BulkResultOut
from resume_agent.api.schemas.jobs import (
    ApplicationOut,
    ApplicationUpsert,
    JobDetail,
    JobPatch,
)
from resume_agent.api.schemas.runs import AddJobTextRequest
from resume_agent.services import board
from resume_agent.services.discovery import ActiveJobQuotaError, add_job_from_text
from resume_agent.tracking.repository import get_job
from resume_agent.tracking.tables import ApplicationStatus, JobStatus

router = APIRouter()


def _job_detail_response(session: Session, job_id: int) -> JobDetail:
    row = board.get_job_detail(session, job_id)
    if row is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return JobDetail.model_validate(row)


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(job_id: int, session: Session = Depends(get_session)):
    return _job_detail_response(session, job_id)


@router.patch("/jobs/{job_id}", response_model=JobDetail)
def patch_job(job_id: int, patch: JobPatch, session: Session = Depends(get_session)):
    if patch.status is not None:
        valid = {s.value for s in JobStatus}
        if patch.status not in valid:
            raise ApiException(
                422, "VALIDATION_ERROR", f"Unknown status '{patch.status}'"
            )
        if board.set_stage(session, job_id, patch.status) is None:
            raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if patch.archived is not None:
        if board.set_archived(session, job_id, patch.archived) is None:
            raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return _job_detail_response(session, job_id)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job_endpoint(
    job_id: int, session: Session = Depends(get_session)
) -> Response:
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if not board.delete(session, job_id):
        raise ApiException(409, "CONFLICT", "Job has progress and cannot be deleted")
    return Response(status_code=204)


def _bulk_filter(body: BulkRequest) -> board.BoardFilter:
    return board.BoardFilter(
        q=body.q,
        source=tuple(body.source),
        status=tuple(body.status_in),
        remote=tuple(body.remote),
        sponsorship=tuple(body.sponsorship),
        seniority=tuple(body.seniority),
        employment_type=tuple(body.employment_type),
        industry=tuple(body.industry),
        country=tuple(body.country),
        region=tuple(body.region),
        city=tuple(body.city),
        company_size=tuple(body.company_size),
        skills=tuple(body.skills),
        min_fit=body.min_fit,
        max_fit=body.max_fit,
        min_salary=body.min_salary,
        stale_days=body.stale_days,
        sort=body.sort_by,
        archived=body.archived,
    )


@router.post("/jobs/bulk", response_model=BulkResultOut)
def bulk_jobs(body: BulkRequest, session: Session = Depends(get_session)):
    if body.action == "setStatus" and not body.status:
        raise ApiException(422, "VALIDATION_ERROR", "status is required for setStatus")
    result = board.bulk_apply(
        session,
        board=body.board,
        action=body.action,
        scope=body.scope,
        board_filter=_bulk_filter(body),
        ids=body.ids,
        status=body.status,
        dry_run=body.dry_run,
    )
    return BulkResultOut.model_validate(result)


@router.put("/jobs/{job_id}/application", response_model=ApplicationOut)
def upsert_application(
    job_id: int, body: ApplicationUpsert, session: Session = Depends(get_session)
):
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    valid = {s.value for s in ApplicationStatus}
    if body.status not in valid:
        raise ApiException(
            422, "VALIDATION_ERROR", f"Unknown application status '{body.status}'"
        )
    app_row = board.upsert_application(
        session, job_id, status=body.status, notes=body.notes
    )
    return ApplicationOut.model_validate(app_row)


@router.post("/jobs", response_model=JobDetail, status_code=201)
def create_manual_job(body: AddJobTextRequest, session: Session = Depends(get_session)):
    try:
        job = add_job_from_text(
            session,
            jd_text=body.jd_text,
            url=body.url,
            company=body.company,
            title=body.title,
            location=body.location,
        )
    except ActiveJobQuotaError as error:
        raise ApiException(429, error.code, str(error)) from error
    if job is None:
        raise ApiException(
            409, "CONFLICT", "Duplicate job (same URL or JD already present)"
        )
    assert job.id is not None
    return _job_detail_response(session, job.id)
