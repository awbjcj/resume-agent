"""Resume-version PDF download + on-demand render (render added in Task 11)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.jobs import ResumeVersionOut
from resume_agent.services.rendering import render_resume_version
from resume_agent.tracking.repository import get_resume_version

router = APIRouter()


@router.get("/resume-versions/{version_id}/pdf")
def download_pdf(version_id: int, session: Session = Depends(get_session)) -> FileResponse:
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    if not version.pdf_path or not Path(version.pdf_path).exists():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this version")
    return FileResponse(
        version.pdf_path, media_type="application/pdf", filename=Path(version.pdf_path).name
    )


@router.post("/resume-versions/{version_id}/render", response_model=ResumeVersionOut)
def render_endpoint(version_id: int, session: Session = Depends(get_session)):
    path = render_resume_version(session, version_id)
    if path is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    return ResumeVersionOut.model_validate(version)
