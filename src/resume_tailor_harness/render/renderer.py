import re
import json
from pathlib import Path

import typst
from pypdf import PdfReader

from resume_tailor_harness.models.resume import ResumeContent


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def output_filename(
    company: str, title: str, date_str: str, qualifier: str | int | None = None
) -> str:
    """Build a slugged PDF filename.

    ``qualifier`` is optional so callers that need stable unique names can avoid
    overwriting another render for the same company/title/date.
    """
    parts = [_slug(company) or "company", _slug(title) or "role", date_str]
    if qualifier is not None:
        qualifier_slug = _slug(str(qualifier))
        if qualifier_slug:
            parts.append(qualifier_slug)
    return f"{'_'.join(parts)}.pdf"


def _page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def render_pdf(
    content: ResumeContent,
    output_path: str | Path,
    template_path: str | Path = "templates/resume.typ",
    *,
    fit_pages: int | None = 1,
    min_zoom: float = 0.82,
    zoom_step: float = 0.03,
    root: str | Path | None = None,
    highlight_terms: list[str] | None = None,
) -> Path:
    """Compile the Typst template with the resume JSON into a PDF file.

    When ``fit_pages`` is set, the template's ``zoom`` factor is swept down from
    1.0 (recompiling each step) until the PDF fits within ``fit_pages`` pages or
    ``min_zoom`` is reached — a readable floor past which we accept an overflow
    rather than produce unreadably small text. Pass ``fit_pages=None`` to render
    once at full size.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = content.model_dump_json()
    source = Path(template_path).resolve()
    resolved_root = Path(root).resolve() if root is not None else source.parent

    zoom = 1.0
    while True:
        sys_inputs = {"data": data, "zoom": f"{zoom:.4f}"}
        if highlight_terms is not None:
            sys_inputs["highlight_terms"] = json.dumps(highlight_terms)
        typst.compile(
            str(source),
            output=str(out),
            root=str(resolved_root),
            sys_inputs=sys_inputs,
        )
        if fit_pages is None or _page_count(out) <= fit_pages or zoom <= min_zoom:
            return out
        zoom = round(zoom - zoom_step, 4)
