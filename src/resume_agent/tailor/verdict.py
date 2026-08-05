from collections.abc import Iterable

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.coverage import CoverageCritique
from resume_agent.tailor.review_config import RESERVED_REVIEWER_NAMES, ReviewConfig

# Gates decided in-process, not by a configured reviewer agent. They ride in the
# critiques list like any gate, so aggregate stays the only verdict constructor.
DETERMINISTIC_GATES = RESERVED_REVIEWER_NAMES

# The default configured gate when the caller has no ReviewConfig to consult
# (e.g. reading a stored version outside a request that loaded one). `fact-check`
# is the gate in both shipped rosters, but the review settings UI lets a user
# mark ANY reviewer as a gate - callers that know which reviewers are actually
# configured as gates for this round must pass `gate_names` instead of relying
# on this default.
DEFAULT_GATE_REVIEWERS = DETERMINISTIC_GATES | frozenset({"fact-check"})


def failing_gate_names(
    critiques: list[ReviewCritique], gate_names: Iterable[str] | None = None
) -> list[str]:
    """Which gates blocked this round, in the order they were recorded.

    `fact_check_passed` on a stored version is the AND of every gate, so on its
    own it cannot say WHICH one failed - and it labelled a deterministic gate
    failure as a fact-check failure on rounds where fact-check never ran.

    `gate_names` should be the configured gate reviewers for the round these
    critiques came from (`{r.name for r in config.reviewers if r.gate}`); it
    defaults to `DEFAULT_GATE_REVIEWERS` only when the caller has no config to
    consult. Deterministic gates are always gates, not configured reviewers.
    """
    gates = DETERMINISTIC_GATES | (
        frozenset(gate_names) if gate_names is not None else DEFAULT_GATE_REVIEWERS
    )
    return [
        critique.reviewer
        for critique in critiques
        if not isinstance(critique, CoverageCritique)
        if critique.reviewer in gates and not critique.passed
    ]


class PanelVerdict(ExtensibleModel):
    passed: bool
    gate_passed: bool
    aggregate_score: int | None
    critiques: list[ReviewCritique] = Field(default_factory=list)


def aggregate(critiques: list[ReviewCritique], config: ReviewConfig) -> PanelVerdict:
    """Combine critiques into one verdict: any failed gate blocks the round.

    Gates are the configured reviewer gates plus the deterministic gates
    (provenance, skill-naming, and numeric-evidence). Each rides in `critiques`,
    so there is a single verdict shape whether or not the panel ran.
    """
    # Coverage is retained in the verdict's critique list for health reporting
    # and persistence, but its runtime marker keeps it out of configured gate
    # and weighted-review selection. A real configured reviewer with the same
    # name therefore remains authoritative.
    decision_critiques = [
        critique for critique in critiques if not isinstance(critique, CoverageCritique)
    ]
    by_name = {c.reviewer: c for c in decision_critiques}

    config_gates = {r.name for r in config.reviewers if r.gate}
    gate_passed = all(
        c.passed
        for c in decision_critiques
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
