"""Canonical company-intelligence models shared by persistence and APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel

CompanyIntelligenceAxis = Literal[
    "strategy",
    "recent_moves",
    "engineering_culture",
    "challenges",
    "competitive_position",
]
CompanySourceType = Literal["official", "independent"]
CompanySourceTier = Literal[
    "company_official",
    "government_or_regulatory",
    "reputable_independent",
    "employee_or_community",
    "other",
]
CompanyVerificationState = Literal["corroborated", "single_source", "inferred"]
CompanyResearchDepth = Literal["quick", "standard", "deep"]


class CompanyIntelligenceSource(ExtensibleModel):
    title: str = ""
    url: str = ""
    publisher: str = ""
    source_type: CompanySourceType = "independent"
    source_tier: CompanySourceTier = "other"
    published_at: datetime | None = None
    last_verified_at: datetime | None = None


class CompanyIntelligenceInsight(ExtensibleModel):
    axis: CompanyIntelligenceAxis
    summary: str = ""
    why_it_matters: str = ""
    citations: list[str] = Field(default_factory=list)
    verification_state: CompanyVerificationState = "single_source"
    as_of: datetime | None = None
    conflicting_evidence: str = ""


class CompanyIntelligenceChangeSet(ExtensibleModel):
    added_axes: list[CompanyIntelligenceAxis] = Field(default_factory=list)
    removed_axes: list[CompanyIntelligenceAxis] = Field(default_factory=list)
    changed_axes: list[CompanyIntelligenceAxis] = Field(default_factory=list)
    added_source_urls: list[str] = Field(default_factory=list)
    removed_source_urls: list[str] = Field(default_factory=list)


class CompanyIntelligenceDraft(ExtensibleModel):
    overview: str = ""
    insights: list[CompanyIntelligenceInsight] = Field(default_factory=list)
    sources: list[CompanyIntelligenceSource] = Field(default_factory=list)


class CompanyIntelligenceEvidence(ExtensibleModel):
    schema_version: int = 2
    normalized_company: str
    display_company: str
    overview: str
    insights: list[CompanyIntelligenceInsight] = Field(default_factory=list)
    sources: list[CompanyIntelligenceSource] = Field(default_factory=list)
    retrieved_at: datetime
    expires_at: datetime
    caveat: str
    version_id: int | None = None
    version_number: int = 1
    previous_version_id: int | None = None
    research_depth: CompanyResearchDepth = "standard"
    changes: CompanyIntelligenceChangeSet = Field(
        default_factory=CompanyIntelligenceChangeSet
    )

    def is_fresh(self, now: datetime) -> bool:
        return self.expires_at > now
