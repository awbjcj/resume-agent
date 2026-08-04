"""Validated historical H-1B evidence contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

HISTORICAL_ONLY_CAVEAT = (
    "Historical H-1B filings do not confirm current sponsorship for this role "
    "or current employer policy."
)
H1B_DISABLED_MESSAGE = (
    "H-1B research is disabled for this workspace. Enable H1B_MCP_ENABLED and "
    "configure an MCP command or URL."
)
H1B_NO_EVIDENCE_MESSAGE = "No H-1B evidence has been checked for this job yet."
H1B_MCP_UNAVAILABLE_REASON = (
    "The H-1B MCP service could not be reached. Check the configured command or URL."
)
H1B_AGENT_UNAVAILABLE_REASON = (
    "The H-1B research agent did not return valid evidence for this company."
)


class H1BCompanyResolution(BaseModel):
    """Validated company-name rewrite used before historical H-1B lookup."""

    status: Literal["resolved", "unchanged", "uncertain"]
    legal_name: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)


class H1BPeriodStat(BaseModel):
    """One fiscal quarter of historical filing figures for a company."""

    period: str = Field(min_length=1, max_length=32)
    filing_count: int | None = Field(default=None, ge=0)
    certified_count: int | None = Field(default=None, ge=0)
    denied_count: int | None = Field(default=None, ge=0)
    wage_summary: dict[str, float] | None = None

    @model_validator(mode="after")
    def validate_outcome_counts(self) -> H1BPeriodStat:
        if (
            self.filing_count is not None
            and self.certified_count is not None
            and self.denied_count is not None
            and self.certified_count + self.denied_count > self.filing_count
        ):
            raise ValueError(
                "certified_count + denied_count cannot exceed filing_count"
            )
        return self


def _rollup(periods: list[H1BPeriodStat], attribute: str) -> int | None:
    """Sum one metric across periods, yielding None when no period reports it."""
    present = [
        value
        for value in (getattr(period, attribute) for period in periods)
        if value is not None
    ]
    return sum(present) if present else None


class H1BSponsorshipEvidence(BaseModel):
    status: Literal["matched", "no_match", "unavailable"]
    normalized_company: str = Field(min_length=1)
    display_company: str | None = None
    fiscal_periods: list[str] = Field(default_factory=list)
    filing_count: int | None = Field(default=None, ge=0)
    certified_count: int | None = Field(default=None, ge=0)
    denied_count: int | None = Field(default=None, ge=0)
    periods: list[H1BPeriodStat] = Field(default_factory=list, max_length=4)
    wage_summary: dict[str, float] | None = None
    source_url: str | None = None
    data_version: str | None = None
    retrieved_at: datetime
    expires_at: datetime
    confidence: float = Field(ge=0, le=1)
    caveat: str
    unavailable_reason: str | None = None

    @field_validator("retrieved_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("H1B timestamps must be timezone-aware")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("H1B source_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("H1B source_url must not contain credentials")
        return value

    @model_validator(mode="after")
    def validate_historical_contract(self) -> H1BSponsorshipEvidence:
        if self.periods:
            labels = [period.period for period in self.periods]
            if len(set(labels)) != len(labels):
                raise ValueError("H1B evidence periods must have unique labels")
            # The rollup is derived, never trusted: a model cannot put a total on
            # screen that disagrees with the parts shown beneath it.
            self.filing_count = _rollup(self.periods, "filing_count")
            self.certified_count = _rollup(self.periods, "certified_count")
            self.denied_count = _rollup(self.periods, "denied_count")
        if self.expires_at <= self.retrieved_at:
            raise ValueError("H1B evidence must expire after retrieval")
        if self.caveat != HISTORICAL_ONLY_CAVEAT:
            raise ValueError("H1B evidence must use the application caveat")
        if self.certified_count is not None and self.filing_count is not None:
            if self.certified_count > self.filing_count:
                raise ValueError("certified_count cannot exceed filing_count")
        if self.denied_count is not None and self.filing_count is not None:
            if self.denied_count > self.filing_count:
                raise ValueError("denied_count cannot exceed filing_count")
        if (
            self.filing_count is not None
            and self.certified_count is not None
            and self.denied_count is not None
            and self.certified_count + self.denied_count > self.filing_count
        ):
            raise ValueError("certified_count + denied_count cannot exceed filing_count")
        return self

    def is_fresh(self, now: datetime) -> bool:
        """Whether this evidence is still inside its cache TTL at ``now``.

        The single definition of "fresh" -- every caller that needs to decide
        whether to reuse cached evidence or label it stale for display goes
        through this instead of re-deriving the ``expires_at`` comparison.
        """
        return self.expires_at > now


class H1BEnrichmentReport(BaseModel):
    by_company: dict[str, H1BSponsorshipEvidence]
    cache_hits: int = Field(default=0, ge=0)
    researched: int = Field(default=0, ge=0)
    unavailable: int = Field(default=0, ge=0)
