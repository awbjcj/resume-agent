from enum import Enum

from pydantic import Field

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
