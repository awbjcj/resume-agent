from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.models.base import ExtensibleModel


class SearchConfig(ExtensibleModel):
    """Discovery criteria + hard-filter thresholds (from config/search.yaml)."""

    keywords: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: list[str] = Field(default_factory=list)
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False
    # Relevance gate (all optional; empty/None means that gate is skipped).
    role_anchors: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    target_role: str | None = None
    # Shared source-narrowing fields used by Adzuna and LinkedIn.
    distance: int | None = None
    max_days_old: int | None = None
    # LinkedIn native filters, mapped to LinkedIn filter codes by the scraper.
    experience_levels: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)

    @field_validator("remote_policy", mode="before")
    @classmethod
    def _coerce_remote_policy(cls, v: Any) -> Any:
        """Accept a legacy bare string (pre-multi-select `search.yaml`/dicts)."""
        if isinstance(v, str):
            v = v.strip()
            return [] if v.lower() in ("", "any") else [v]
        return v


def load_search_config(path: str | Path) -> SearchConfig:
    return SearchConfig.model_validate(load_yaml(path))
