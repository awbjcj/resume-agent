from pathlib import Path

from pydantic import Field

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class SearchConfig(ExtensibleModel):
    """Discovery criteria + hard-filter thresholds (from config/search.yaml)."""

    keywords: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: str | None = None
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


def load_search_config(path: str | Path) -> SearchConfig:
    return SearchConfig.model_validate(load_yaml(path))
