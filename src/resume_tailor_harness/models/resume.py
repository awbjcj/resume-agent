from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.profile import Contact, Education, Language


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


class TailoredPublication(ExtensibleModel):
    title: str
    venue: str | None = None
    date: str | None = None
    authors: list[str] = Field(default_factory=list)
    url: str | None = None
    provenance: str  # id of the source Publication


class TailoredCertification(ExtensibleModel):
    name: str
    issuer: str | None = None
    date: str | None = None
    url: str | None = None
    provenance: str  # id of the source Certification


class TailoredAward(ExtensibleModel):
    name: str
    issuer: str | None = None
    date: str | None = None
    description: str | None = None
    provenance: str  # id of the source Award


class TailoredVolunteer(ExtensibleModel):
    organization: str
    role: str | None = None
    start: str | None = None
    end: str | None = None
    bullets: list[TailoredBullet] = Field(default_factory=list)
    provenance: str  # id of the source Volunteer record


class ResumeContent(ExtensibleModel):
    """Structured, fact-locked resume content. The renderer turns this into a PDF;
    the LLM never emits markup."""

    contact: Contact  # carried verbatim from ProfileFacts (no invention)
    summary: str | None = None
    # Fact ids the summary draws on. The summary is prose with no per-claim
    # provenance field, so without these the gate cannot check it and the
    # evidence reviewer only ever sees facts cited by OTHER sections - which
    # makes a true summary claim look unsupported. Empty is allowed at this
    # model level so resumes stored before this field existed still
    # deserialize; `tailor.provenance.check_provenance` is what actually
    # requires a nonempty summary to carry provenance ids, and it only runs
    # against freshly produced tailor/revise rounds, never on load.
    summary_provenance: list[str] = Field(default_factory=list)
    experience: list[TailoredExperience] = Field(default_factory=list)
    projects: list[TailoredProject] = Field(default_factory=list)
    skills: dict[str, list[TailoredSkill]] = Field(default_factory=dict)
    education: list[Education] = Field(default_factory=list)  # carried verbatim
    publications: list[TailoredPublication] = Field(default_factory=list)
    certifications: list[TailoredCertification] = Field(default_factory=list)
    awards: list[TailoredAward] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)  # carried verbatim
    volunteer: list[TailoredVolunteer] = Field(default_factory=list)
    section_order: list[str] | None = None  # optional per-JD ordering hint
