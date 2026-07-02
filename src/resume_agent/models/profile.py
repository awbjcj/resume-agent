from typing import Literal

from pydantic import Field, model_validator

from resume_agent.models.base import ExtensibleModel, FactItem, Source


class Link(ExtensibleModel):
    label: str
    url: str


class Contact(ExtensibleModel):
    name: str
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    willing_to_relocate: bool = False
    work_authorization: str | None = None  # e.g. "needs H-1B sponsorship"
    links: list[Link] = Field(default_factory=list)


class Bullet(FactItem):
    text: str


class Skill(FactItem):
    name: str
    aliases: list[str] = Field(default_factory=list)
    context: str | None = None
    inferred: bool = False
    evidence_fact_ids: list[str] = Field(default_factory=list)
    category: Literal["hard", "soft", "domain"] | None = None

    @model_validator(mode="after")
    def inferred_has_evidence(self) -> "Skill":
        if self.inferred and (self.category is None or not self.evidence_fact_ids):
            raise ValueError("an inferred skill requires category and evidence_fact_ids")
        return self


class Experience(FactItem):
    company: str
    title: str
    employment_type: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None  # None = current role
    current: bool = False
    bullets: list[Bullet] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)


class Education(FactItem):
    institution: str
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None
    gpa: str | None = None
    honors: list[str] = Field(default_factory=list)
    relevant_coursework: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)


class Project(FactItem):
    name: str
    description: str | None = None
    role: str | None = None
    tech: list[str] = Field(default_factory=list)
    url: str | None = None
    repo_url: str | None = None
    highlights: list[str] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    stars: int | None = None
    forks: int | None = None
    primary_language: str | None = None
    languages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    homepage_url: str | None = None
    last_updated: str | None = None
    is_fork: bool | None = None


class Certification(FactItem):
    name: str
    issuer: str | None = None
    date: str | None = None
    credential_id: str | None = None
    url: str | None = None


class Publication(FactItem):
    title: str
    venue: str | None = None
    date: str | None = None
    authors: list[str] = Field(default_factory=list)
    url: str | None = None


class Award(FactItem):
    name: str
    issuer: str | None = None
    date: str | None = None
    description: str | None = None


class Language(FactItem):
    language: str
    proficiency: str | None = None


class Volunteer(FactItem):
    organization: str
    role: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None


class GitHubProfile(FactItem):
    source: Source = Source.github
    username: str | None = None
    bio: str | None = None
    followers: int | None = None
    public_repos: int | None = None
    account_created_at: str | None = None
    top_languages: list[str] = Field(default_factory=list)
    total_stars: int | None = None


class ProfileFacts(ExtensibleModel):
    """The fact-lock: the ONLY facts any tailoring is allowed to draw from."""

    contact: Contact
    summary: str | None = None
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: dict[str, list[Skill]] = Field(default_factory=dict)
    certifications: list[Certification] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    volunteer: list[Volunteer] = Field(default_factory=list)
    github_profile: GitHubProfile | None = None
    interests: list[str] = Field(default_factory=list)
