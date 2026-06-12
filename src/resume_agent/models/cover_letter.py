from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import Contact


class CoverLetterParagraph(ExtensibleModel):
    """A body paragraph. ``provenance`` lists the ProfileFacts fact ids it draws on."""

    text: str
    provenance: list[str] = Field(default_factory=list)


class CoverLetterContent(ExtensibleModel):
    """Structured, fact-locked cover letter."""

    contact: Contact
    recipient: str | None = None
    greeting: str
    paragraphs: list[CoverLetterParagraph] = Field(default_factory=list)
    closing: str
