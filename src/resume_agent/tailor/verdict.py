from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER
from resume_agent.tailor.review_config import ReviewConfig

# Gates decided in-process, not by a configured reviewer agent. They ride in the
# critiques list like any gate, so aggregate stays the only verdict constructor.
DETERMINISTIC_GATES = frozenset({PROVENANCE_REVIEWER})


class PanelVerdict(ExtensibleModel):
    passed: bool
    gate_passed: bool
    aggregate_score: int
    critiques: list[ReviewCritique] = Field(default_factory=list)


def aggregate(critiques: list[ReviewCritique], config: ReviewConfig) -> PanelVerdict:
    """Combine critiques into one verdict: any failed gate blocks the round.

    Gates are the configured reviewer gates plus the deterministic gates
    (provenance). Each rides in `critiques`, so there is a single verdict shape
    whether or not the panel ran.
    """
    by_name = {c.reviewer: c for c in critiques}

    config_gates = {r.name for r in config.reviewers if r.gate}
    gate_passed = all(
        c.passed
        for c in critiques
        if c.reviewer in config_gates or c.reviewer in DETERMINISTIC_GATES
    )

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
