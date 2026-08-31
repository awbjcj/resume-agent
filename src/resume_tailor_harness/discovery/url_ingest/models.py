from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class PageContent:
    """Raw page bytes plus how they were obtained."""

    html: str
    final_url: str
    rendered: bool


class ExtractedJob(BaseModel):
    """Fields pulled from a posting page; the LLM and parsers share this shape."""

    company: str | None = None
    title: str | None = None
    location: str | None = None
    jd_text: str = ""
