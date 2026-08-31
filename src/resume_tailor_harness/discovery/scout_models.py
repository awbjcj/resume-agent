"""Shared value models for the Source and Search scouts."""

from urllib.parse import urlsplit

from resume_tailor_harness.models.base import ExtensibleModel


class Citation(ExtensibleModel):
    url: str = ""
    title: str = ""


def is_http_url(value: str) -> bool:
    """Whether an untrusted string is a renderable external HTTP(S) URL."""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def citation_rows(citations: list[Citation]) -> list[dict[str, str]]:
    """Project only safe evidence links across the service boundary."""
    return [
        {"url": citation.url.strip(), "title": citation.title.strip()}
        for citation in citations
        if is_http_url(citation.url)
    ]
