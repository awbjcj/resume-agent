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


class H1BSponsorshipEvidence(BaseModel):
    status: Literal["matched", "no_match", "unavailable"]
    normalized_company: str = Field(min_length=1)
    display_company: str | None = None
    fiscal_periods: list[str] = Field(default_factory=list)
    filing_count: int | None = Field(default=None, ge=0)
    certified_count: int | None = Field(default=None, ge=0)
    wage_summary: dict[str, float] | None = None
    source_url: str | None = None
    data_version: str | None = None
    retrieved_at: datetime
    expires_at: datetime
    confidence: float = Field(ge=0, le=1)
    caveat: str

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
        if self.expires_at <= self.retrieved_at:
            raise ValueError("H1B evidence must expire after retrieval")
        if self.caveat != HISTORICAL_ONLY_CAVEAT:
            raise ValueError("H1B evidence must use the application caveat")
        if self.certified_count is not None and self.filing_count is not None:
            if self.certified_count > self.filing_count:
                raise ValueError("certified_count cannot exceed filing_count")
        return self


class H1BEnrichmentReport(BaseModel):
    by_company: dict[str, H1BSponsorshipEvidence]
    cache_hits: int = Field(default=0, ge=0)
    researched: int = Field(default=0, ge=0)
    unavailable: int = Field(default=0, ge=0)
