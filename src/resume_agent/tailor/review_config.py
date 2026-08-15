from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel
from resume_agent.tailor.numeric_evidence import NUMERIC_EVIDENCE_REVIEWER
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER
from resume_agent.tailor.skill_naming import SKILL_NAMING_REVIEWER

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
    """One-page guidance handed to the tailor and surfaced to reviewers.

    Every field below bounds prose EXCEPT the two skill fields, which set a
    floor. That asymmetry is the point: bullets and skills do not cost the same
    page space. A bullet is a line; the skills section renders one comma-joined
    line per category, so ~40 entries cost about five lines. Without a stated
    skills target the writer applied the same "prefer the most relevant, drop
    the rest" pressure to both, and shipped ~17 of a ~335-skill profile.
    """

    max_experiences: int = 4
    max_projects: int = 2
    max_evidence_owners: int = 5
    max_bullets_per_role: int = 5
    max_bullets_per_project: int = 3
    target_total_bullets: int = 20
    # A target, not a cap: the writer is asked to reach it, not to stop there.
    target_skills: int = 40
    max_skills_per_category: int = 12


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
