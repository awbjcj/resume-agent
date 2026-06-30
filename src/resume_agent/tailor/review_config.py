from pathlib import Path

from pydantic import Field

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


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
    early_stop_on_regression: bool = False
    length_budget: LengthBudget = Field(default_factory=LengthBudget)
    style_guide_path: str = "config/style_guide.md"


def load_review_config(path: str | Path) -> ReviewConfig:
    return ReviewConfig.model_validate(load_yaml(path))
