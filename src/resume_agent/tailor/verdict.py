from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER
from resume_agent.tailor.review_config import ReviewConfig

# Gates decided in-process, not by a configured reviewer agent. They ride in the
# critiques list like any gate, so aggregate stays the only verdict constructor.
DETERMINISTIC_GATES = frozenset({PROVENANCE_REVIEWER})

# Every gate that can block a round. `provenance` is deterministic; `fact-check`
# is the configured integrity gate in both shipped rosters and is the one
# reviewer that may not be edited. Stored critiques do not record gate-ness, so
# read-side surfaces name the failing gate through this set rather than guessing
# from severity - an advisory reviewer may also raise a blocking issue.
GATE_REVIEWERS = DETERMINISTIC_GATES | frozenset({"fact-check"})


def failing_gate_names(critiques: list[ReviewCritique]) -> list[str]:
    """Which gates blocked this round, in the order they were recorded.

    `fact_check_passed` on a stored version is the AND of every gate, so on its
    own it cannot say WHICH one failed - and it labelled a provenance-only
    failure as a fact-check failure on rounds where fact-check never ran.
    """
    return [
        critique.reviewer
        for critique in critiques
        if critique.reviewer in GATE_REVIEWERS and not critique.passed
    ]


class PanelVerdict(ExtensibleModel):
    passed: bool
    gate_passed: bool
    aggregate_score: int | None
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
    # No weighted critique means the advisory panel never produced a score. That
    # is unknown, not zero: reporting 0 reads as "terrible resume" when it means
    # "never measured", and a config with only gate reviewers has no quality bar
    # to clear at all.
    aggregate_score = (
        round(sum(weight * score for weight, score in weighted) / total_weight)
        if total_weight
        else None
    )

    passed = gate_passed and (
        aggregate_score is None or aggregate_score >= config.score_threshold
    )
    return PanelVerdict(
        passed=passed,
        gate_passed=gate_passed,
        aggregate_score=aggregate_score,
        critiques=critiques,
    )
