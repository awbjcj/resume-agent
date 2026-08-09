from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel


CoverageState = Literal["covered", "adjacent", "gap"]
OwnerKind = Literal["experience", "project"]
PortfolioStatus = Literal["planned", "deterministic_fallback", "inherited"]
RequirementKind = Literal["skill", "responsibility", "seniority"]


class EvidenceFactCandidate(ExtensibleModel):
    fact_id: str
    text: str
    source_order: int = 0
    metric_count: int = 0
    direct_must_requirements: list[str] = Field(default_factory=list)
    direct_requirements: list[str] = Field(default_factory=list)
    adjacent_requirements: list[str] = Field(default_factory=list)


class EvidenceOwnerCandidate(ExtensibleModel):
    owner_id: str
    owner_kind: OwnerKind
    label: str
    start: str | None = None
    end: str | None = None
    current: bool = False
    source_order: int = 0
    strength: float = 0.0
    suggested_bullet_count: int = 1
    direct_must_requirements: list[str] = Field(default_factory=list)
    direct_requirements: list[str] = Field(default_factory=list)
    adjacent_requirements: list[str] = Field(default_factory=list)
    facts: list[EvidenceFactCandidate] = Field(default_factory=list)


class EvidenceCatalog(ExtensibleModel):
    owners: list[EvidenceOwnerCandidate] = Field(default_factory=list)


class PortfolioRequirement(ExtensibleModel):
    text: str
    kind: RequirementKind = "skill"
    priority: int = Field(default=100, ge=1)
    coverage: CoverageState = "gap"
    supporting_fact_ids: list[str] = Field(default_factory=list)
    approved_terms: list[str] = Field(default_factory=list)
    core: bool = False
    rationale: str = ""


class PortfolioSelection(ExtensibleModel):
    owner_id: str
    owner_kind: OwnerKind
    selected_fact_ids: list[str] = Field(default_factory=list)
    requirement_texts: list[str] = Field(default_factory=list)
    rank: int = Field(default=100, ge=1)
    bullet_budget: int = Field(default=1, ge=0)
    bridge: bool = False
    rationale: str = ""


class PortfolioOmission(ExtensibleModel):
    owner_id: str
    owner_kind: OwnerKind
    rationale: str


class EvidenceExcerpt(ExtensibleModel):
    fact_id: str
    owner_id: str
    owner_kind: OwnerKind
    text: str


class EvidencePortfolio(ExtensibleModel):
    """Frozen, validated strategy for one tailoring attempt.

    The portfolio is strategy data, never a source of candidate truth. Every
    written claim still has to cite and pass checks against ``ProfileFacts``.
    """

    status: PortfolioStatus = "planned"
    warning: str | None = None
    requirements: list[PortfolioRequirement] = Field(default_factory=list)
    selections: list[PortfolioSelection] = Field(default_factory=list)
    selected_skill_fact_ids: list[str] = Field(default_factory=list)
    highlight_terms: list[str] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)
    omissions: list[PortfolioOmission] = Field(default_factory=list)
    evidence_excerpts: list[EvidenceExcerpt] = Field(default_factory=list)
