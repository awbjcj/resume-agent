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


class CompanyIntelligenceSource(ExtensibleModel):
    title: str = ""
    url: str = ""
    publisher: str = ""
    source_type: CompanySourceType = "independent"


class CompanyIntelligenceInsight(ExtensibleModel):
    axis: CompanyIntelligenceAxis
    summary: str = ""
    why_it_matters: str = ""
    citations: list[str] = Field(default_factory=list)


class CompanyIntelligenceDraft(ExtensibleModel):
    overview: str = ""
    insights: list[CompanyIntelligenceInsight] = Field(default_factory=list)
    sources: list[CompanyIntelligenceSource] = Field(default_factory=list)


class CompanyIntelligenceEvidence(ExtensibleModel):
    normalized_company: str
    display_company: str
    overview: str
    insights: list[CompanyIntelligenceInsight] = Field(default_factory=list)
    sources: list[CompanyIntelligenceSource] = Field(default_factory=list)
    retrieved_at: datetime
    expires_at: datetime
    caveat: str

    def is_fresh(self, now: datetime) -> bool:
        return self.expires_at > now
