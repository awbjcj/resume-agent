from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.tailor.numeric_evidence import NUMERIC_EVIDENCE_REVIEWER
from resume_tailor_harness.tailor.provenance import PROVENANCE_REVIEWER
from resume_tailor_harness.tailor.skill_naming import SKILL_NAMING_REVIEWER

# These names are emitted by deterministic in-process gates and must not be
# claimed by a configured/model-backed reviewer. Each is imported from the
# module that emits it rather than restated here, so a rename cannot leave a
# gate name unreserved while a test that restates the literals still passes.
# ``must-have-coverage`` is intentionally absent: it is also a supported
# configured reviewer name.
RESERVED_REVIEWER_NAMES = frozenset(
    {PROVENANCE_REVIEWER, SKILL_NAMING_REVIEWER, NUMERIC_EVIDENCE_REVIEWER}
)


def _flag_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


class ReviewerSpec(ExtensibleModel):
    name: str
    gate: bool = False
    weight: int = 1
    model_tier: str = "mid"  # cheap | mid | premium
    score_bands: bool = False


class LengthBudget(ExtensibleModel):
    """Page and evidence-owner guidance handed to tailoring and reviewers.

    Every field below bounds prose EXCEPT the two skill fields, which set a
    floor. That asymmetry is the point: bullets and skills do not cost the same
    page space. A bullet is a line; the skills section renders one comma-joined
    line per category, so ~40 entries cost about five lines. Without a stated
    skills target the writer applied the same "prefer the most relevant, drop
    the rest" pressure to both, and shipped ~17 of a ~335-skill profile.
    """

    page_target: int = Field(default=2, ge=1)
    max_experiences: int = Field(default=5, ge=0)
    max_projects: int = Field(default=4, ge=0)
    max_evidence_owners: int = Field(default=8, ge=0)
    min_bullets_per_role: int = Field(default=5, ge=0)
    max_bullets_per_role: int = Field(default=7, ge=0)
    min_bullets_per_project: int = Field(default=4, ge=0)
    max_bullets_per_project: int = Field(default=6, ge=0)
    target_total_bullets: int = Field(default=40, ge=0)
    min_aspects_per_owner: int = Field(default=3, ge=0)
    # A target, not a cap: the writer is asked to reach it, not to stop there.
    target_skills: int = 40
    max_skills_per_category: int = 12

    @model_validator(mode="before")
    @classmethod
    def _backfill_legacy_floors(cls, data: object) -> object:
        """Keep cap-only YAML and callers valid after floors were introduced.

        A pre-depth budget could intentionally set a cap of one or two.  Its
        missing floor should mean that same achievable cap, not the new default
        floor of five. Explicitly supplied floor/cap pairs still go through the
        stricter validator below.
        """
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for floor_key, cap_key, default_floor in (
            ("min_bullets_per_role", "max_bullets_per_role", 5),
            ("min_bullets_per_project", "max_bullets_per_project", 4),
        ):
            if floor_key in result or not isinstance(result.get(cap_key), int):
                continue
            if result[cap_key] < default_floor:
                result[floor_key] = result[cap_key]
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


class ReviewConfig(ExtensibleModel):
    max_rounds: int = Field(default=3, ge=1)
    score_threshold: int = 85
    reviewers: list[ReviewerSpec] = Field(default_factory=list)
    evidence_portfolio_enabled: bool = False
    # One-release compatibility spelling. A before-validator mirrors either
    # explicitly supplied key onto the other and rejects contradictory YAML.
    match_plan_enabled: bool = False
    merged_advisory: bool = False
    tailor_tier: Literal["cheap", "mid", "premium"] = "premium"
    reviser_tier: Literal["cheap", "mid", "premium"] = "premium"
    early_stop_on_regression: bool = False
    # Extra rounds granted when a round failed ONLY on provenance ids. Fixing a
    # citation is cheap and should not consume one of the `max_rounds` quality
    # passes. 0 reproduces the pre-fix round counting exactly.
    provenance_retry_budget: int = Field(default=1, ge=0)
    length_budget: LengthBudget = Field(default_factory=LengthBudget)
    style_guide_path: str = "config/style_guide.md"

    @property
    def portfolio_enabled(self) -> bool:
        """Canonical runtime value, including legacy objects copied without validation."""
        return self.evidence_portfolio_enabled or self.match_plan_enabled

    @model_validator(mode="before")
    @classmethod
    def _portfolio_flag_alias(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        has_new = "evidence_portfolio_enabled" in data
        has_old = "match_plan_enabled" in data
        new_value = _flag_bool(data.get("evidence_portfolio_enabled"))
        old_value = _flag_bool(data.get("match_plan_enabled"))
        if (
            has_new
            and has_old
            and None not in (new_value, old_value)
            and new_value != old_value
        ):
            raise ValueError(
                "evidence_portfolio_enabled conflicts with legacy match_plan_enabled"
            )
        if has_new and not has_old:
            return {**data, "match_plan_enabled": data["evidence_portfolio_enabled"]}
        if has_old and not has_new:
            return {**data, "evidence_portfolio_enabled": data["match_plan_enabled"]}
        return data

    @model_validator(mode="after")
    def _reject_reserved_reviewer_names(self) -> "ReviewConfig":
        reserved = sorted(
            {
                spec.name
                for spec in self.reviewers
                if spec.name in RESERVED_REVIEWER_NAMES
            }
        )
        if reserved:
            names = ", ".join(repr(name) for name in reserved)
            raise ValueError(
                f"reviewer names are reserved for deterministic gates: {names}"
            )
        return self


def load_review_config(path: str | Path) -> ReviewConfig:
    return ReviewConfig.model_validate(load_yaml(path))
