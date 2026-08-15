"""Resume-version PDF download + on-demand render (render added in Task 11)."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_agent.api.artifacts import raise_for_delete_result
from resume_agent.api.deps import get_config_store, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.config import ReviewConfigDoc
from resume_agent.api.schemas.evidence_portfolio import EvidencePortfolioOut
from resume_agent.api.schemas.jobs import (
    ApplicationOut,
    ArtifactDeleteOut,
    ArtifactDeleteRequest,
    ResumeVersionOut,
)
from resume_agent.render.export import resume_download_name
from resume_agent.models.evidence_portfolio import EvidencePortfolio
from resume_agent.models.resume import ResumeContent
from resume_agent.services.board import (
    delete_resume_versions,
    deselect_resume_version,
    select_resume_version,
)
from resume_agent.services.rendering import render_resume_version
from resume_agent.tenancy.storage import resolve_artifact_pdf
from resume_agent.tracking.repository import get_job, get_resume_version

router = APIRouter()
link_router = APIRouter()


def _realized_portfolio_fact_ids(content: ResumeContent) -> set[str]:
    return {
        *(
            fact_id
            for experience in content.experience
            for fact_id in (
                experience.provenance,
                *(bullet.provenance for bullet in experience.bullets),
            )
        ),
        *(
            fact_id
            for project in content.projects
            for fact_id in (
                project.provenance,
                *(bullet.provenance for bullet in project.bullets),
            )
        ),
        *(skill.provenance for entries in content.skills.values() for skill in entries),
    }


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


@router.get(
    "/resume-versions/{version_id}/evidence-portfolio",
    response_model=EvidencePortfolioOut,
)
def evidence_portfolio_endpoint(
    version_id: int, session: Session = Depends(get_session)
) -> EvidencePortfolioOut:
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    if version.evidence_portfolio_json is None:
        raise ApiException(
            404,
            "EVIDENCE_PORTFOLIO_NOT_AVAILABLE",
            "This legacy resume version has no evidence portfolio.",
        )
    portfolio = EvidencePortfolio.model_validate(version.evidence_portfolio_json)
    content = ResumeContent.model_validate(version.content_json or {})
    allowed = {
        *(selection.owner_id for selection in portfolio.selections),
        *(
            fact_id
            for selection in portfolio.selections
            for fact_id in selection.selected_fact_ids
        ),
        *portfolio.selected_skill_fact_ids,
    }
    outside = sorted(_realized_portfolio_fact_ids(content) - allowed)
    return EvidencePortfolioOut.from_portfolio(
        portfolio, realized_outside_fact_ids=outside
    )


@router.post("/jobs/{job_id}/select-resume/{version_id}", response_model=ApplicationOut)
def select_resume_endpoint(
    job_id: int, version_id: int, session: Session = Depends(get_session)
):
    application = select_resume_version(session, job_id, version_id)
    if application is None:
        raise ApiException(404, "NOT_FOUND", "Job or resume version not found")
    return ApplicationOut.model_validate(application)


@router.delete("/jobs/{job_id}/select-resume", response_model=ApplicationOut)
def deselect_resume_endpoint(job_id: int, session: Session = Depends(get_session)):
    """Clear the application's resume selection -- the way past the delete gate."""
    application = deselect_resume_version(session, job_id)
    if application is None:
        raise ApiException(404, "NOT_FOUND", "No application for this job")
    return ApplicationOut.model_validate(application)


@router.delete("/resume-versions/{version_id}", status_code=204)
def delete_resume_version_endpoint(
    version_id: int, session: Session = Depends(get_session)
) -> Response:
    raise_for_delete_result(
        delete_resume_versions(session, [version_id]), noun="Resume version"
    )
    return Response(status_code=204)


@router.post("/resume-versions/bulk-delete", response_model=ArtifactDeleteOut)
def bulk_delete_resume_versions_endpoint(
    body: ArtifactDeleteRequest, session: Session = Depends(get_session)
) -> ArtifactDeleteOut:
    result = delete_resume_versions(session, body.ids)
    raise_for_delete_result(result, noun="Resume version")
    return ArtifactDeleteOut(deleted=result.deleted)
