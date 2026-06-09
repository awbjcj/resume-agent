import re
from pathlib import Path

import typst

from resume_agent.models.resume import ResumeContent


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def output_filename(company: str, title: str, date_str: str) -> str:
    return f"{_slug(company)}_{_slug(title)}_{date_str}.pdf"


def render_pdf(
    content: ResumeContent,
    output_path: str | Path,
    template_path: str | Path = "templates/resume.typ",
) -> Path:
    """Compile the Typst template with the resume JSON into a PDF file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(
        str(template_path),
        output=str(out),
        sys_inputs={"data": content.model_dump_json()},
    )
    return out
