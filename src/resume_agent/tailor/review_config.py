from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


# These names are emitted by deterministic in-process gates and must not be
# claimed by a configured/model-backed reviewer. ``must-have-coverage`` is
# intentionally absent: it is also a supported configured reviewer name.
RESERVED_REVIEWER_NAMES = frozenset(
    {"provenance", "skill-naming", "numeric-evidence"}
)


class ReviewerSpec(ExtensibleModel):
    name: str
    gate: bool = False
    weight: int = 1
    model_tier: str = "mid"  # cheap | mid | premium
    score_bands: bool = False


class LengthBudget(ExtensibleModel):
    """One-page guidance handed to the tailor and surfaced to reviewers."""

    max_experiences: int = 4
    max_bullets_per_role: int = 5
    target_total_bullets: int = 20


class ReviewConfig(ExtensibleModel):
    max_rounds: int = Field(default=3, ge=1)
    score_threshold: int = 85
    reviewers: list[ReviewerSpec] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def _reject_reserved_reviewer_names(self) -> "ReviewConfig":
        reserved = sorted(
            {spec.name for spec in self.reviewers if spec.name in RESERVED_REVIEWER_NAMES}
        )
        if reserved:
            names = ", ".join(repr(name) for name in reserved)
            raise ValueError(
                f"reviewer names are reserved for deterministic gates: {names}"
            )
        return self


def load_review_config(path: str | Path) -> ReviewConfig:
    return ReviewConfig.model_validate(load_yaml(path))
