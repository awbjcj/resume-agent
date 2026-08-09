from pathlib import Path
from typing import Callable

from sqlmodel import Session

from resume_agent.models.resume import ResumeContent
from resume_agent.models.evidence_portfolio import EvidencePortfolio
from resume_agent.render.export import export_job_artifacts, job_dir, resume_pdf_name
from resume_agent.render.render_config import RenderConfig
from resume_agent.render.renderer import render_pdf
from resume_agent.render.templates import template_path_for
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.paths import resolve_tenant_path
from resume_agent.tracking.repository import (
    get_job,
    get_resume_version,
    save_job,
    save_resume_version,
)
from resume_agent.tracking.tables import JobStatus, ResumeVersion

RenderFn = Callable[..., Path]


def render_version(
    session: Session,
    version_id: int,
    config: RenderConfig,
    render_fn: RenderFn = render_pdf,
) -> Path | None:
    """Render one resume version to PDF, store its path, mark the job rendered."""
    version: ResumeVersion | None = get_resume_version(session, version_id)
    if version is None:
        return None
    job = get_job(session, version.job_id)

    content = ResumeContent.model_validate(version.content_json or {})
    context = current_context()
    output_base: str | Path = (
        context.paths.output_dir if context is not None else config.output_dir
    )
    out_dir = (
        job_dir(output_base, job)
        if job is not None
        else resolve_tenant_path(output_base)
    )
    out_path = out_dir / resume_pdf_name(version)

    render_kwargs: dict[str, int | list[str] | None] = {
        "fit_pages": 1 if config.fit_one_page else None
    }
    if version.evidence_portfolio_json is not None:
        portfolio = EvidencePortfolio.model_validate(version.evidence_portfolio_json)
        render_kwargs["highlight_terms"] = portfolio.highlight_terms
    render_fn(content, out_path, template_path_for(config), **render_kwargs)

    version.pdf_path = str(out_path)
    save_resume_version(session, version)
    if job is not None:
        assert job.id is not None
        job.status = JobStatus.rendered.value
        save_job(session, job)
        export_job_artifacts(session, job.id, base=output_base)
    return out_path
