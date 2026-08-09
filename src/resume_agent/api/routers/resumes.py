"""Resume-version PDF download + on-demand render (render added in Task 11)."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_agent.api.deps import get_config_store, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.config import ReviewConfigDoc
from resume_agent.api.schemas.jobs import (
    ApplicationOut,
    ResumeVersionOut,
)
from resume_agent.render.export import resume_download_name
from resume_agent.services.board import select_resume_version
from resume_agent.services.rendering import render_resume_version
from resume_agent.tenancy.storage import resolve_artifact_pdf
from resume_agent.tracking.repository import get_job, get_resume_version

router = APIRouter()
link_router = APIRouter()


@link_router.get("/resume-versions/{version_id}/pdf")
def download_pdf(
    version_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    path = resolve_artifact_pdf(version.pdf_path)
    if path is None:
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this version")
    job = get_job(session, version.job_id)
    filename = resume_download_name(job, version) if job is not None else path.name
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/resume-versions/{version_id}/preview")
def preview_pdf(
    version_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    """Serve the rendered PDF inline so the SPA can show it in a preview modal."""

    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    path = resolve_artifact_pdf(version.pdf_path)
    if path is None:
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this version")
    # Streamed, not buffered. ``FileResponse`` only emits a disposition when a
    # ``filename`` is passed, so ``inline`` is set explicitly here -- an
    # attachment disposition would defeat the preview.
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; object-src 'self'",
        },
    )


@router.post("/resume-versions/{version_id}/render", response_model=ResumeVersionOut)
def render_endpoint(
    version_id: int, request: Request, session: Session = Depends(get_session)
):
    path = render_resume_version(session, version_id)
    if path is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    version_out = ResumeVersionOut.model_validate(version)
    review_doc = cast(ReviewConfigDoc, get_config_store(request).get("review"))
    version_out.apply_gate_names({r.name for r in review_doc.reviewers if r.gate})
    return version_out


@router.post("/jobs/{job_id}/select-resume/{version_id}", response_model=ApplicationOut)
def select_resume_endpoint(
    job_id: int, version_id: int, session: Session = Depends(get_session)
):
    application = select_resume_version(session, job_id, version_id)
    if application is None:
        raise ApiException(404, "NOT_FOUND", "Job or resume version not found")
    return ApplicationOut.model_validate(application)
