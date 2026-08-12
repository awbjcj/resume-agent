"""Typed config documents — the wire contract for /api/config/{domain}.

Each Doc mirrors one YAML file's shape (snake_case on disk, camelCase on the
wire via CamelModel). Field defaults ARE the file defaults: a missing file
serves these values, and the TUI/CLI keep reading the same YAML.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from resume_agent.api.schemas.base import CamelModel


class SearchConfigDoc(CamelModel):
    keywords: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: list[str] = Field(default_factory=list)
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False
    role_anchors: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    target_role: str | None = None
    distance: int | None = None
    max_days_old: int | None = None
    experience_levels: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)

    @field_validator("remote_policy", mode="before")
    @classmethod
    def _coerce_remote_policy(cls, v: Any) -> Any:
        """Accept a legacy bare string (pre-multi-select `search.yaml`/dicts)."""
        if v is None:
            return []
        if isinstance(v, str):
            v = v.strip()
            return [] if v.lower() in ("", "any") else [v]
        return v


class NormalizeLocationsRequest(CamelModel):
    raw: list[str] = Field(default_factory=list)


class NormalizeLocationsResponse(CamelModel):
    normalized: list[str] = Field(default_factory=list)


class ReviewerEntry(CamelModel):
    name: str
    gate: bool = False
    weight: int = 1
    model_tier: str = "mid"
    score_bands: bool = False


class LengthBudget(CamelModel):
    max_experiences: int = 4
    max_projects: int = 2
    max_evidence_owners: int = 5
    max_bullets_per_role: int = 5
    max_bullets_per_project: int = 3
    target_total_bullets: int = 20


def _default_reviewers() -> list[ReviewerEntry]:
    return [
        ReviewerEntry(name="fact-check", gate=True, weight=0, model_tier="premium"),
        ReviewerEntry(
            name="ats-keyword", gate=False, weight=1, model_tier="mid", score_bands=True
        ),
        ReviewerEntry(
            name="recruiter", gate=False, weight=1, model_tier="mid", score_bands=True
        ),
        ReviewerEntry(
            name="hiring-manager",
            gate=False,
            weight=1,
            model_tier="premium",
            score_bands=True,
        ),
        ReviewerEntry(
            name="concision", gate=False, weight=1, model_tier="mid", score_bands=True
        ),
    ]


class ReviewConfigDoc(CamelModel):
    max_rounds: int = 3
    score_threshold: int = 85
    merged_advisory: bool = False
    tailor_tier: Literal["cheap", "mid", "premium"] = "premium"
    reviser_tier: Literal["cheap", "mid", "premium"] = "premium"
    evidence_portfolio_enabled: bool = False
    reviewers: list[ReviewerEntry] = Field(default_factory=_default_reviewers)
    provenance_retry_budget: int = Field(default=1, ge=0)
    length_budget: LengthBudget | None = None


class PruneConfigDoc(CamelModel):
    fit_threshold: int = 40
    stale_days: int = 60
    retention_days: int = 30
    enable_rejected: bool = True
    enable_low_fit: bool = True
    enable_stale: bool = True


class RenderConfigDoc(CamelModel):
    template: str = "classic"
    fit_one_page: bool = True


class StyleGuideDoc(CamelModel):
    content: str = ""


class ProfileConfigDoc(CamelModel):
    github_username: str | None = None
    github_repo_allow: list[str] = Field(default_factory=list)
    github_repo_deny: list[str] = Field(default_factory=list)
    github_repo_limit: int = Field(default=20, ge=1, le=100)


DOMAIN_SCHEMAS: dict[str, type[CamelModel]] = {
    "search": SearchConfigDoc,
    "review": ReviewConfigDoc,
    "review_deep": ReviewConfigDoc,
    "prune": PruneConfigDoc,
    "render": RenderConfigDoc,
    "style_guide": StyleGuideDoc,
    "profile": ProfileConfigDoc,
}
