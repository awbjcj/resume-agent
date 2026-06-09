from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import Contact, Education


class TailoredBullet(ExtensibleModel):
    """A resume bullet. ``provenance`` MUST point to a ProfileFacts fact id."""

    text: str
    provenance: str  # id of the source Bullet/Experience/Project in ProfileFacts


class TailoredSkill(ExtensibleModel):
    """A selected skill. ``provenance`` MUST point to a ProfileFacts Skill id."""

    name: str
    provenance: str
    context: str | None = None


class TailoredExperience(ExtensibleModel):
    company: str
    title: str
    location: str | None = None
    start: str | None = None
    end: str | None = None
    bullets: list[TailoredBullet] = Field(default_factory=list)
    provenance: str  # id of the source Experience


class TailoredProject(ExtensibleModel):
    name: str
    description: str | None = None
    tech: list[str] = Field(default_factory=list)
    bullets: list[TailoredBullet] = Field(default_factory=list)
    provenance: str  # id of the source Project


class ResumeContent(ExtensibleModel):
    """Structured, fact-locked resume content. The renderer turns this into a PDF;
    the LLM never emits markup."""

    contact: Contact  # carried verbatim from ProfileFacts (no invention)
    summary: str | None = None
    experience: list[TailoredExperience] = Field(default_factory=list)
    projects: list[TailoredProject] = Field(default_factory=list)
    skills: dict[str, list[TailoredSkill]] = Field(default_factory=dict)
    education: list[Education] = Field(default_factory=list)  # carried verbatim
