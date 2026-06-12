from pathlib import Path
from typing import Callable

import typst
from sqlmodel import Session

from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.render.renderer import output_filename
from resume_agent.tracking.repository import get_cover_letter, get_job, save_cover_letter
from resume_agent.tracking.tables import utcnow

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
    company = (job.company if job else None) or "company"
    title = (job.title if job else None) or "role"
    filename = output_filename(
        company, title, utcnow().strftime("%Y%m%d"), f"cl{cover.id or cover_letter_id}"
    )
    out_path = Path(output_dir) / filename

    render_fn(content, out_path, template_path)

    cover.pdf_path = str(out_path)
    save_cover_letter(session, cover)
    return out_path
