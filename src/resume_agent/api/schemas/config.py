"""Typed config documents — the wire contract for /api/config/{domain}.

Each Doc mirrors one YAML file's shape (snake_case on disk, camelCase on the
wire via CamelModel). Field defaults ARE the file defaults: a missing file
serves these values, and the TUI/CLI keep reading the same YAML.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from resume_agent.api.schemas.base import CamelModel
from resume_agent.tailor.review_config import LengthBudget as DomainLengthBudget
from resume_agent.tailor.review_config import ReviewConfig as DomainReviewConfig


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


def _domain_default(model: type[Any], field: str) -> Any:
    """A DTO default taken from the domain model, never a restated literal.

    These DTOs used to copy the numbers by hand. That is the same drift the
    model-tier defaults hit: the domain model moves, the wire contract quietly
    keeps serving last release's numbers, and a test that restates the literals
    too keeps passing.
    """
    return model.model_fields[field].default


def _budget_default(field: str) -> int:
    default = _domain_default(DomainLengthBudget, field)
    assert isinstance(default, int)
    return default


class LengthBudget(CamelModel):
    # Plain defaults, resolved at class-definition time - NOT default_factory.
    # A factory is invisible to JSON Schema, which silently stripped every
    # `default` from the published OpenAPI contract and cost API consumers the
    # documented values.
    page_target: int = Field(default=_budget_default("page_target"), ge=1)
    max_experiences: int = Field(default=_budget_default("max_experiences"), ge=0)
    max_projects: int = Field(default=_budget_default("max_projects"), ge=0)
    max_evidence_owners: int = Field(
        default=_budget_default("max_evidence_owners"), ge=0
    )
    min_bullets_per_role: int = Field(
        default=_budget_default("min_bullets_per_role"), ge=0
    )
    max_bullets_per_role: int = Field(
        default=_budget_default("max_bullets_per_role"), ge=0
    )
    min_bullets_per_project: int = Field(
        default=_budget_default("min_bullets_per_project"), ge=0
    )
    max_bullets_per_project: int = Field(
        default=_budget_default("max_bullets_per_project"), ge=0
    )
    target_total_bullets: int = Field(
        default=_budget_default("target_total_bullets"), ge=0
    )
    min_aspects_per_owner: int = Field(
        default=_budget_default("min_aspects_per_owner"), ge=0
    )
    target_skills: int = _budget_default("target_skills")
    max_skills_per_category: int = _budget_default("max_skills_per_category")

    @model_validator(mode="before")
    @classmethod
    def _backfill_legacy_floors(cls, data: Any) -> Any:
        """Accept cap-only payloads emitted by clients before depth floors."""
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for floor_key, floor_alias, cap_key, cap_alias in (
            (
                "min_bullets_per_role",
                "minBulletsPerRole",
                "max_bullets_per_role",
                "maxBulletsPerRole",
            ),
            (
                "min_bullets_per_project",
                "minBulletsPerProject",
                "max_bullets_per_project",
                "maxBulletsPerProject",
            ),
        ):
            if floor_key in result or floor_alias in result:
                continue
            cap = result.get(cap_key, result.get(cap_alias))
            if isinstance(cap, int) and cap < _budget_default(floor_key):
                result[floor_key] = cap
        return result

    @model_validator(mode="after")
    def _validate_bullet_ranges(self) -> "LengthBudget":
        if self.min_bullets_per_role > self.max_bullets_per_role:
            raise ValueError("min_bullets_per_role cannot exceed max_bullets_per_role")
        if self.min_bullets_per_project > self.max_bullets_per_project:
            raise ValueError(
                "min_bullets_per_project cannot exceed max_bullets_per_project"
            )
        return self


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
    """Every field `ReviewConfig` reads, because `put` rewrites the whole file.

    `YamlConfigStore.put` serializes this DTO over the YAML rather than merging
    into it, so a domain field missing here is not merely un-editable — it is
    **deleted** the first time anything on the page is saved. That is how
    `early_stop_on_regression: true` silently reverted to `false` on the fast
    roster. `match_plan_enabled` is deliberately still absent: it is the
    deprecated spelling, and `ReviewConfig` mirrors it from
    `evidence_portfolio_enabled` on load, so omitting it drops a legacy key
    rather than losing a setting.
    """

    max_rounds: int = 3
    score_threshold: int = 85
    merged_advisory: bool = False
    tailor_tier: Literal["cheap", "mid", "premium"] = "premium"
    reviser_tier: Literal["cheap", "mid", "premium"] = "premium"
    evidence_portfolio_enabled: bool = False
    early_stop_on_regression: bool = _domain_default(
        DomainReviewConfig, "early_stop_on_regression"
    )
    reviewers: list[ReviewerEntry] = Field(default_factory=_default_reviewers)
    provenance_retry_budget: int = Field(default=1, ge=0)
    style_guide_path: str = _domain_default(DomainReviewConfig, "style_guide_path")
    # Not optional, because `ReviewConfig.length_budget` is not: a `null` here
    # round-tripped to `length_budget: null` on disk, which `ReviewConfig`
    # rejects outright, so turning the budget "off" in the UI broke every
    # subsequent tailor run at config load. A plain default (not
    # `default_factory`) keeps the values in the published JSON Schema.
    length_budget: LengthBudget = LengthBudget()

    @field_validator("length_budget", mode="before")
    @classmethod
    def _heal_null_budget(cls, v: Any) -> Any:
        """Repair a workspace whose `review.yaml` already holds `null`.

        Those files exist: the removed on/off switch wrote them. Coercing to
        defaults on read means such a workspace serves its settings page and
        saves itself clean, instead of 500ing on GET forever.
        """
        return LengthBudget() if v is None else v


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
    # `template_path` and `output_dir` are deliberately NOT here: rendering is
    # template-id based on the web (see render/CLAUDE.md) and those two stay
    # runtime-only CLI fields. They are preserved across a save by
    # `YamlConfigStore.put`, which no longer drops keys a DTO does not own.


class StyleGuideDoc(CamelModel):
    content: str = ""


class ProfileConfigDoc(CamelModel):
    # `resume_path` is deliberately absent: the setup wizard writes it
    # (`setup/yaml_gen.py::build_profile_sources`) and `profile/corpus.py`'s
    # legacy migration reads it, but the settings UI manages sources through
    # the corpus registry rather than this one path. `YamlConfigStore.put`
    # preserves it rather than this DTO re-exposing it.
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
