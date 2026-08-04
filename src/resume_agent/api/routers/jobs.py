"""Single-job endpoints: detail (this task), mutations (Task 10)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlmodel import Session

from resume_agent.api.deps import (
    get_config_store,
    get_engine,
    get_interview_dir,
    get_run_manager,
    get_session,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.launch import launch, session_work
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.bulk import BulkRequest, BulkResultOut
from resume_agent.api.schemas.config import ReviewConfigDoc
from resume_agent.api.schemas.jobs import (
    ApplicationOut,
    ApplicationUpsert,
    JobDetail,
    JobPatch,
    H1BSponsorshipOut,
    H1BSponsorshipEvidenceOut,
    JobsImportError,
    JobsImportReportOut,
)
from resume_agent.config import Settings
from resume_agent.h1b.cache import load_company_evidence
from resume_agent.h1b.models import (
    H1B_DISABLED_MESSAGE,
    H1B_NO_EVIDENCE_MESSAGE,
    H1BSponsorshipEvidence,
)
from resume_agent.h1b.service import check_job_sponsorship
from resume_agent.api.schemas.runs import AddJobTextRequest, RunOut
from resume_agent.api.uploads import UploadTooLargeError, read_upload
from resume_agent.services import board
from resume_agent.services.discovery import ActiveJobQuotaError, add_job_from_text
from resume_agent.taxonomy.industries import normalize_company
from resume_agent.tenancy.limits import DEFAULT_MAX_ACTIVE_JOBS, active_limit
from resume_agent.tracking.repository import get_job
from resume_agent.tracking.tables import ApplicationStatus, JobStatus

router = APIRouter()


@router.post("/jobs/import", response_model=JobsImportReportOut)
def import_jobs_endpoint(
    file: UploadFile, session: Session = Depends(get_session)
) -> JobsImportReportOut:
    from resume_agent.services.jobs_import import (
        InvalidJobsFileError,
        UnsupportedJobsFormatError,
        import_jobs_file,
    )

    try:
        data = read_upload(file, max_bytes=10 * 1024 * 1024)
        report = import_jobs_file(
            session,
            file.filename or "",
            data,
            max_active_jobs=active_limit("max_active_jobs", DEFAULT_MAX_ACTIVE_JOBS),
        )
    except UploadTooLargeError as exc:
        raise ApiException(413, "UPLOAD_TOO_LARGE", str(exc)) from exc
    except UnsupportedJobsFormatError as exc:
        raise ApiException(400, "UNSUPPORTED_FORMAT", str(exc)) from exc
    except InvalidJobsFileError as exc:
        raise ApiException(400, "INVALID_FILE", str(exc)) from exc
    return JobsImportReportOut(
        added=report.added,
        upgraded=report.upgraded,
        skipped=report.skipped,
        errors=[JobsImportError(row=row, reason=reason) for row, reason in report.errors],
    )


def _job_detail_response(
    session: Session, job_id: int, request: Request, settings: Settings
) -> JobDetail:
    row = board.get_job_detail(session, job_id)
    if row is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    detail = JobDetail.model_validate(row)
    if not settings.h1b_mcp_enabled:
        detail.h1b_sponsorship = H1BSponsorshipOut(
            capability="disabled",
            message=H1B_DISABLED_MESSAGE,
        )
    else:
        job = get_job(session, job_id)
        evidence = None
        if job is not None:
            key = normalize_company(job.company)
            if key:
                evidence = load_company_evidence(session, [job.company]).get(key)
        detail.h1b_sponsorship = _h1b_sponsorship_response(evidence)
    review_doc = cast(ReviewConfigDoc, get_config_store(request).get("review"))
    gate_names = {r.name for r in review_doc.reviewers if r.gate}
    for version in detail.resume_versions:
        version.apply_gate_names(gate_names)
    return detail


def _h1b_sponsorship_response(
    evidence: H1BSponsorshipEvidence | None,
    *,
    now: datetime | None = None,
) -> H1BSponsorshipOut:
    if evidence is None:
        return H1BSponsorshipOut(
            capability="unavailable",
            message=H1B_NO_EVIDENCE_MESSAGE,
        )
    # Expired evidence still renders -- historical filings do not rot. The server
    # owns "now" for every other TTL decision, so it owns this label too.
    stale = not evidence.is_fresh(now or datetime.now(timezone.utc))
    if evidence.status == "unavailable":
        return H1BSponsorshipOut(
            capability="unavailable",
            evidence=H1BSponsorshipEvidenceOut.from_evidence(evidence),
            message=evidence.unavailable_reason,
            stale=stale,
        )
    return H1BSponsorshipOut(
        capability="available",
        evidence=H1BSponsorshipEvidenceOut.from_evidence(evidence),
        stale=stale,
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(
    job_id: int,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
    return _job_detail_response(session, job_id, request, settings)


@router.post(
    "/jobs/{job_id}/h1b-sponsorship",
    response_model=RunOut,
    status_code=202,
)
def check_h1b_sponsorship(
    job_id: int,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    mgr: RunManager = Depends(get_run_manager),
) -> RunOut:
    job = get_job(session, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if not settings.h1b_mcp_enabled:
        raise ApiException(409, "H1B_DISABLED", H1B_DISABLED_MESSAGE)
    if not normalize_company(job.company):
        raise ApiException(
            422,
            "VALIDATION_ERROR",
            "A company is required before checking H-1B sponsorship",
        )

    engine = get_engine(request)

    def do_check(worker_session: Session, reporter):
        reporter.begin(1, f"Checking H-1B sponsorship for job #{job_id}")
        job_row = get_job(worker_session, job_id)
        if job_row is None:
            raise ValueError(f"Job #{job_id} not found")
        asyncio.run(check_job_sponsorship(worker_session, job_row, settings=settings))
        reporter.step(1)
        return {"jobId": job_id}

    return launch(
        mgr,
        "h1bSponsorship",
        session_work(engine, do_check),
        singleton_key=f"h1b-sponsorship:{job_id}",
        singleton_conflict="raise",
        meta={"jobId": job_id},
        busy_message="An H-1B check is already running for this job",
    )


@router.patch("/jobs/{job_id}", response_model=JobDetail)
def patch_job(
    job_id: int,
    patch: JobPatch,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
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
    return _job_detail_response(session, job_id, request, settings)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job_endpoint(
    job_id: int, request: Request, session: Session = Depends(get_session)
) -> Response:
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if not board.delete(session, job_id):
        raise ApiException(409, "CONFLICT", "Job has progress and cannot be deleted")
    from resume_agent.interview.store import delete_sessions_for_job

    delete_sessions_for_job(get_interview_dir(request), job_id)
    return Response(status_code=204)


def _bulk_filter(body: BulkRequest) -> board.BoardFilter:
    return board.BoardFilter(
        q=body.q,
        reject_reason=body.reject_reason,
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
        stale_min_days=body.stale_min_days,
        sort=body.sort_by,
        preset=body.preset,
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
def create_manual_job(
    body: AddJobTextRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
):
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
    return _job_detail_response(session, job.id, request, settings)
