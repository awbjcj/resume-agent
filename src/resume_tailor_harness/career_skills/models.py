"""Closed career-skill and run-provenance contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentFamily(StrEnum):
    JOB_ANALYSIS = "job_analysis"
    RESUME_AUTHORING = "resume_authoring"
    RESUME_REVIEW = "resume_review"
    COVER_LETTER = "cover_letter"
    INTERVIEW = "interview"
    CAREER_LAB = "career_lab"
    INTERNAL_PROFILE = "internal_profile"
    SPONSORSHIP_RESEARCH = "sponsorship_research"


class SkillRef(BaseModel):
    name: str
    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    family: AgentFamily


SkillUseStage = Literal[
    "generated", "reviewed", "revised", "opening", "turn", "debrief"
]


class SkillUse(BaseModel):
    skill_ref: SkillRef
    stage: SkillUseStage
    used_at: datetime
    model_id: str
    prompt_policy_version: str


class AgentRunMeta(BaseModel):
    agent_family: AgentFamily
    prompt_policy_version: str
    model_id: str
    skill_ref: SkillRef | None = None


class ResumeAuthoringSkillName(StrEnum):
    ACADEMIC_CV_BUILDER = "academic-cv-builder"
    ACADEMIC_RESEARCH_CV = "academic-research-cv"
    CREATIVE_PORTFOLIO_RESUME = "creative-portfolio-resume"
    EXECUTIVE_LEADERSHIP_RESUME = "executive-leadership-resume"
    EXECUTIVE_RESUME_WRITER = "executive-resume-writer"
    RESUME_BULLET_WRITER = "resume-bullet-writer"
    RESUME_CUSTOMIZER = "resume-customizer"
    RESUME_QUANTIFIER = "resume-quantifier"
    RESUME_SECTION_BUILDER = "resume-section-builder"
    RESUME_TAILOR = "resume-tailor"
    SOFTWARE_ENGINEER_RESUME = "software-engineer-resume"
    TECH_RESUME_OPTIMIZER = "tech-resume-optimizer"


class CoverLetterSkillName(StrEnum):
    GENERATOR = "cover-letter-generator"
    WRITER = "cover-letter-writer"


class CareerLabSkillName(StrEnum):
    APPLICATION_FORM_FILLER = "application-form-filler"
    CAREER_CHANGER_TRANSLATOR = "career-changer-translator"
    CAREER_PIVOT_PLANNER = "career-pivot-planner"
    COLD_EMAIL_WRITER = "cold-email-writer"
    COMPENSATION_NEGOTIATOR = "compensation-negotiator"
    LINKEDIN_PROFILE_BOOSTER = "linkedin-profile-booster"
    LINKEDIN_PROFILE_OPTIMIZER = "linkedin-profile-optimizer"
    OFFER_COMPARISON_ANALYZER = "offer-comparison-analyzer"
    PORTFOLIO_CASE_STUDY = "portfolio-case-study"
    PORTFOLIO_CASE_STUDY_WRITER = "portfolio-case-study-writer"
    REFERENCE_LIST_BUILDER = "reference-list-builder"
    SALARY_NEGOTIATION_PREP = "salary-negotiation-prep"


class SkillManifestEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str
    source_type: Literal["github", "local"] = Field(alias="sourceType")
    reviewed_ref: str = Field(alias="reviewedRef")
    skill_path: str = Field(alias="skillPath")
    computed_hash: str = Field(alias="computedHash", pattern=r"^[0-9a-f]{64}$")
    local_version: str = Field(alias="localVersion")
    family: AgentFamily
    uses: frozenset[str]
    visibility: Literal["public", "internal"]


class SkillManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: Literal[2]
    hash_mode: Literal["utf8-lf-v1"] = Field(alias="hashMode")
    skills: dict[str, SkillManifestEntry]


class SkillCapability(BaseModel):
    name: str
    description: str
    family: AgentFamily
    uses: list[str]
    is_available: bool
    unavailable_reason: str | None = None


class JobAnalysisMeta(BaseModel):
    criteria: AgentRunMeta | None = None
    fit: AgentRunMeta | None = None
    h1b_evidence_id: int | None = None
    h1b_evidence_snapshot: dict[str, object] | None = None


def read_skill_uses(raw: object) -> list[SkillUse]:
    """Read persisted skill uses without silently accepting corrupt metadata."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("skill uses metadata must be a list")
    return [SkillUse.model_validate(value) for value in raw]


def read_job_analysis_meta(raw: object) -> JobAnalysisMeta | None:
    """Read job analysis metadata; ``None`` is the legacy representation."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("job analysis metadata must be an object")
    return JobAnalysisMeta.model_validate(raw)
