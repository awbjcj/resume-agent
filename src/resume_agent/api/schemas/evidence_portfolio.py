from typing import Literal

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.models.evidence_portfolio import EvidencePortfolio


class PortfolioRequirementOut(CamelModel):
    text: str
    kind: Literal["skill", "responsibility", "seniority"]
    priority: int
    coverage: Literal["covered", "adjacent", "gap"]
    supporting_fact_ids: list[str] = Field(default_factory=list)
    approved_terms: list[str] = Field(default_factory=list)
    core: bool = False
    rationale: str = ""


class PortfolioSelectionOut(CamelModel):
    owner_id: str
    owner_kind: Literal["experience", "project"]
    selected_fact_ids: list[str] = Field(default_factory=list)
    requirement_texts: list[str] = Field(default_factory=list)
    rank: int
    bullet_budget: int
    bridge: bool = False
    rationale: str = ""


class PortfolioOmissionOut(CamelModel):
    owner_id: str
    owner_kind: Literal["experience", "project"]
    rationale: str


class EvidenceExcerptOut(CamelModel):
    fact_id: str
    owner_id: str
    owner_kind: Literal["experience", "project"]
    text: str


class EvidencePortfolioOut(CamelModel):
    status: Literal["planned", "deterministic_fallback", "inherited"]
    warning: str | None = None
    requirements: list[PortfolioRequirementOut] = Field(default_factory=list)
    selections: list[PortfolioSelectionOut] = Field(default_factory=list)
    selected_skill_fact_ids: list[str] = Field(default_factory=list)
    highlight_terms: list[str] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)
    omissions: list[PortfolioOmissionOut] = Field(default_factory=list)
    evidence_excerpts: list[EvidenceExcerptOut] = Field(default_factory=list)
    realized_outside_fact_ids: list[str] = Field(default_factory=list)

    @classmethod
    def from_portfolio(
        cls,
        portfolio: EvidencePortfolio,
        *,
        realized_outside_fact_ids: list[str] | None = None,
    ) -> "EvidencePortfolioOut":
        payload = portfolio.model_dump(mode="json")
        payload["realized_outside_fact_ids"] = realized_outside_fact_ids or []
        return cls.model_validate(payload)

