from pathlib import Path


def read_resume_text(path: str | Path) -> str:
    """Extract plain text from a .pdf, .docx, or .txt resume."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".txt":
        return p.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix == ".docx":
        return _read_docx(p)
    raise ValueError(f"Unsupported resume format: {suffix or '(none)'} (use .pdf, .docx, or .txt)")


def _read_pdf(p: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(p))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(p: Path) -> str:
    from docx import Document

    doc = Document(str(p))
    parts = [para.text for para in doc.paragraphs]
    # Many resume templates lay out content in tables; doc.paragraphs skips those.
    parts += [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
    return "\n".join(parts)
