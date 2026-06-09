from pathlib import Path

from pydantic import Field

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class ReviewerSpec(ExtensibleModel):
    name: str
    gate: bool = False
    weight: int = 1
    model_tier: str = "mid"  # cheap | mid | premium


class ReviewConfig(ExtensibleModel):
    max_rounds: int = 3
    score_threshold: int = 85
    reviewers: list[ReviewerSpec] = Field(default_factory=list)


def load_review_config(path: str | Path) -> ReviewConfig:
    return ReviewConfig.model_validate(load_yaml(path))
