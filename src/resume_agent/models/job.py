from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from resume_agent.models.base import ExtensibleModel


class SponsorshipSignal(str, Enum):
    """What the JD says about visa sponsorship. ``silent`` => uncertain (keep + flag)."""

    offered = "offered"
    denied = "denied"
    silent = "silent"


class Seniority(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    staff = "staff"
    principal = "principal"


class EmploymentType(str, Enum):
    full_time = "full_time"
    contract = "contract"
    internship = "internship"
    part_time = "part_time"


class SalaryRange(ExtensibleModel):
    minimum: int | None = None
    maximum: int | None = None
    currency: str = "USD"
    period: str = "year"  # year | month | hour


class JobCriteria(ExtensibleModel):
    """Structured fields extracted from a raw job description."""

    sponsorship_signal: SponsorshipSignal = SponsorshipSignal.silent
    seniority: Seniority | None = None
    employment_type: EmploymentType | None = None
    tech_stack: list[str] = Field(default_factory=list)
    industry: str | None = None
    company_size: str | None = None
    yoe_min: int | None = None
    salary_range: SalaryRange | None = None
    remote_policy: str | None = None  # remote | hybrid | onsite
    location: str | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)


class SalaryRangeExtract(BaseModel):
    """LLM-facing salary schema: every field required, nullable for unknown.

    Deliberately *not* an :class:`ExtensibleModel` -- the ``schema_version`` /
    ``extra`` plumbing only matters for persistence and would bloat the schema
    Anthropic compiles.
    """

    model_config = ConfigDict(extra="forbid")

    minimum: int | None
    maximum: int | None
    currency: str | None
    period: str | None


class JobCriteriaExtract(BaseModel):
    """LLM-facing mirror of :class:`JobCriteria` for structured extraction.

    Anthropic's structured-output grammar compiler roughly doubles its state
    space for every *optional* field, and nested optionals compound until the
    schema is rejected with ``Schema is too complex``. Making every field
    required (still nullable, so the model can say "unknown") drops the optional
    count to zero and keeps the request within Anthropic's limits. The parsed
    result is mapped onto the persisted :class:`JobCriteria` via
    :meth:`to_criteria`.
    """

    model_config = ConfigDict(extra="forbid")

    sponsorship_signal: SponsorshipSignal
    seniority: Seniority | None
    employment_type: EmploymentType | None
    tech_stack: list[str]
    industry: str | None
    company_size: str | None
    yoe_min: int | None
    salary_range: SalaryRangeExtract | None
    remote_policy: str | None
    location: str | None
    must_have_skills: list[str]
    nice_to_have_skills: list[str]

    def to_criteria(self) -> JobCriteria:
        """Map the lean extraction result onto the persisted domain model."""
        salary = None
        if self.salary_range is not None:
            sr = self.salary_range
            salary = SalaryRange(
                minimum=sr.minimum,
                maximum=sr.maximum,
                currency=sr.currency or "USD",
                period=sr.period or "year",
            )
        return JobCriteria(
            sponsorship_signal=self.sponsorship_signal,
            seniority=self.seniority,
            employment_type=self.employment_type,
            tech_stack=self.tech_stack,
            industry=self.industry,
            company_size=self.company_size,
            yoe_min=self.yoe_min,
            salary_range=salary,
            remote_policy=self.remote_policy,
            location=self.location,
            must_have_skills=self.must_have_skills,
            nice_to_have_skills=self.nice_to_have_skills,
        )
