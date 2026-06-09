from pathlib import Path
from typing import Callable

from sqlmodel import Session

from resume_agent.models.resume import ResumeContent
from resume_agent.render.render_config import RenderConfig
from resume_agent.render.renderer import output_filename, render_pdf
from resume_agent.tracking.repository import get_job, get_resume_version, save_job, save_resume_version
from resume_agent.tracking.tables import JobStatus, ResumeVersion, utcnow

RenderFn = Callable[[ResumeContent, str | Path, str | Path], Path]


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
    company = (job.company if job else None) or "company"
    title = (job.title if job else None) or "role"
    filename = output_filename(company, title, utcnow().strftime("%Y%m%d"))
    out_path = Path(config.output_dir) / filename

    render_fn(content, out_path, config.template_path)

    version.pdf_path = str(out_path)
    save_resume_version(session, version)
    if job is not None:
        job.status = JobStatus.rendered.value
        save_job(session, job)
    return out_path
