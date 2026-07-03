from pathlib import Path

SUPPORTED_SUFFIXES = frozenset(
    {".pdf", ".docx", ".txt", ".md", ".pptx", ".xlsx", ".html"}
)

# Bump whenever the conversion backend or its configuration changes: the
# fragment cache is keyed on source bytes, so a converter change alters the
# text the extractor sees without changing the file hash.
CONVERTER_VERSION = 1

_converter = None


def _markitdown():
    global _converter
    if _converter is None:
        from markitdown import MarkItDown

        _converter = MarkItDown(enable_plugins=False)
    return _converter


def read_document_text(path: str | Path) -> str:
    """Extract markdown-ish plain text from a supported profile source document."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        return p.read_text(encoding="utf-8")
    if suffix in SUPPORTED_SUFFIXES:
        return _markitdown().convert(str(p)).text_content
    supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
    raise ValueError(f"Unsupported document format: {suffix or '(none)'} (use {supported})")


read_resume_text = read_document_text
