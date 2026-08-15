"""Closed value models used by the deterministic Scout source resolver."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel


ResolutionStatus = Literal["verified", "unverified", "conflict", "failed"]
ResolutionReason = Literal[
    "VERIFIED_FIRST_PARTY",
    "VERIFIED_PROVIDER_METADATA",
    "SEARCH_RATE_LIMITED",
    "SEARCH_BUDGET_EXHAUSTED",
    "OFFICIAL_SITE_UNREACHABLE",
    "ATS_NOT_FOUND",
    "OWNERSHIP_NOT_PROVEN",
    "ATS_CONFLICT",
    "RESOLUTION_TIMEOUT",
    "UNSAFE_URL",
]


class SourceEvidence(ExtensibleModel):
    kind: str
    source_url: str
    target_url: str = ""
    summary: str = ""


class CrawlCandidate(ExtensibleModel):
    url: str
    strong_first_party: bool = False
    evidence: list[SourceEvidence] = Field(default_factory=list)


class CrawlReport(ExtensibleModel):
    requested_url: str
    final_first_party_url: str = ""
    first_party_verified: bool = False
    candidates: list[CrawlCandidate] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    error_code: ResolutionReason | None = None


class CompanySourceResolution(ExtensibleModel):
    company: str
    requested_url: str
    canonical_board_url: str = ""
    ats: str | None = None
    token: str | None = None
    role_count: int | None = None
    status: ResolutionStatus = "failed"
    reason_code: ResolutionReason = "ATS_NOT_FOUND"
    evidence: list[SourceEvidence] = Field(default_factory=list)
    searched_families: list[str] = Field(default_factory=list)
    unsearched_families: list[str] = Field(default_factory=list)
