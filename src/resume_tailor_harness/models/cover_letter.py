from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.profile import Contact


class CoverLetterParagraph(ExtensibleModel):
    """A body paragraph. ``provenance`` lists the ProfileFacts fact ids it draws on."""

    text: str
    provenance: list[str] = Field(default_factory=list)


class CoverLetterContent(ExtensibleModel):
    """Structured, fact-locked cover letter."""

    contact: Contact
    greeting: str
    paragraphs: list[CoverLetterParagraph] = Field(default_factory=list)
    closing: str
    recipient: str | None = None
