from pathlib import Path
from typing import Callable

import typst
from sqlmodel import Session

from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.render.export import cover_letter_pdf_name, export_job_artifacts, job_dir
from resume_agent.tracking.repository import get_cover_letter, get_job, save_cover_letter

TEMPLATE = "templates/cover_letter.typ"
RenderFn = Callable[[CoverLetterContent, str | Path, str | Path], Path]


def render_cover_letter_pdf(
    content: CoverLetterContent,
    output_path: str | Path,
    template_path: str | Path = TEMPLATE,
) -> Path:
    """Compile the cover-letter Typst template with JSON content into a PDF."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(
        str(template_path),
        output=str(out),
        sys_inputs={"data": content.model_dump_json()},
    )
    return out


def render_cover_letter(
    session: Session,
    cover_letter_id: int,
    output_dir: str | Path = "output",
    template_path: str | Path = TEMPLATE,
    render_fn: RenderFn = render_cover_letter_pdf,
) -> Path | None:
    """Render a stored cover letter to PDF and persist its path."""
    cover = get_cover_letter(session, cover_letter_id)
    if cover is None:
        return None
    job = get_job(session, cover.job_id)
    content = CoverLetterContent.model_validate(cover.content_json or {})
    out_dir = job_dir(output_dir, job) if job is not None else Path(output_dir)
    out_path = out_dir / cover_letter_pdf_name(cover)

    render_fn(content, out_path, template_path)

    cover.pdf_path = str(out_path)
    save_cover_letter(session, cover)
    if job is not None:
        assert job.id is not None
        export_job_artifacts(session, job.id, base=output_dir)
    return out_path
