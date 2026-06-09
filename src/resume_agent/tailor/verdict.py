from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig


class PanelVerdict(ExtensibleModel):
    passed: bool
    gate_passed: bool
    aggregate_score: int
    critiques: list[ReviewCritique] = Field(default_factory=list)


def aggregate(critiques: list[ReviewCritique], config: ReviewConfig) -> PanelVerdict:
    """Combine critiques: gate reviewers are blocking; the rest are a weighted average."""
    by_name = {c.reviewer: c for c in critiques}

    gate_names = [r.name for r in config.reviewers if r.gate and r.name in by_name]
    gate_passed = all(by_name[name].passed for name in gate_names)

    weighted = [
        (r.weight, by_name[r.name].score)
        for r in config.reviewers
        if not r.gate and r.weight > 0 and r.name in by_name
    ]
    total_weight = sum(weight for weight, _ in weighted)
    aggregate_score = (
        round(sum(weight * score for weight, score in weighted) / total_weight) if total_weight else 0
    )

    passed = gate_passed and aggregate_score >= config.score_threshold
    return PanelVerdict(
        passed=passed,
        gate_passed=gate_passed,
        aggregate_score=aggregate_score,
        critiques=critiques,
    )
