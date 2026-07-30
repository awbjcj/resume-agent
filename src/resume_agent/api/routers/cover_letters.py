from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.jobs import ApplicationOut
from resume_agent.render.export import cover_letter_download_name
from resume_agent.services.board import select_cover_letter
from resume_agent.tenancy.storage import TenantPathError, artifact_path
from resume_agent.tracking.repository import get_cover_letter, get_job

router = APIRouter()
link_router = APIRouter()


@router.post(
    "/jobs/{job_id}/select-cover-letter/{cover_letter_id}",
    response_model=ApplicationOut,
)
def select_cover_letter_endpoint(
    job_id: int, cover_letter_id: int, session: Session = Depends(get_session)
):
    application = select_cover_letter(session, job_id, cover_letter_id)
    if application is None:
        raise ApiException(404, "NOT_FOUND", "Job or cover letter not found")
    return ApplicationOut.model_validate(application)


@link_router.get("/cover-letters/{cover_letter_id}/pdf")
def download_cover_letter_pdf(
    cover_letter_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    cover_letter = get_cover_letter(session, cover_letter_id)
    if cover_letter is None:
        raise ApiException(
            404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found"
        )
    try:
        path = artifact_path(cover_letter.pdf_path) if cover_letter.pdf_path else None
    except TenantPathError:
        path = None
    if path is None or not path.is_file():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this cover letter")
    job = get_job(session, cover_letter.job_id)
    filename = (
        cover_letter_download_name(job, cover_letter) if job is not None else path.name
    )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
    )
