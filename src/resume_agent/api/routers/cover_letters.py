from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.jobs import ApplicationOut, CoverLetterOut, ReviseRequest
from resume_agent.services.board import select_cover_letter
from resume_agent.services.cover_letter_revision import revise_cover_letter_version
from resume_agent.tracking.repository import get_cover_letter

router = APIRouter()
link_router = APIRouter()


@router.post("/cover-letters/{cover_letter_id}/revise", response_model=CoverLetterOut)
def revise_cover_letter_endpoint(
    cover_letter_id: int, body: ReviseRequest, session: Session = Depends(get_session)
):
    cover_letter = revise_cover_letter_version(
        session, cover_letter_id, body.instruction
    )
    if cover_letter is None:
        raise ApiException(
            404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found"
        )
    return CoverLetterOut.model_validate(cover_letter)


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
    if not cover_letter.pdf_path or not Path(cover_letter.pdf_path).exists():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this cover letter")
    return FileResponse(
        cover_letter.pdf_path,
        media_type="application/pdf",
        filename=Path(cover_letter.pdf_path).name,
    )
