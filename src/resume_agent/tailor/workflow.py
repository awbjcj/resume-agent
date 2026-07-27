import asyncio
import time
from collections.abc import Mapping

from pydantic import Field

from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.profile.matrix import SkillMatchContext
from resume_agent.tailor.panel import arun_panel, run_panel
from resume_agent.tailor.match_plan import (
    amatch_plan,
    compose_match_plan_input,
    match_plan,
    normalize_match_plan,
)
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER, provenance_critique
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.tailoring import (
    arevise,
    atailor,
    compose_revise_input,
    compose_tailor_input,
    revise,
    tailor,
)
from resume_agent.tailor.verdict import PanelVerdict, aggregate


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict
    stage_seconds: dict[str, float] = Field(default_factory=dict)


def _has_regressed(rounds: list[TailorRound]) -> bool:
    current = rounds[-1]
    # An unscored round carries no quality bar, so it is not a baseline to
    # regress from and cannot itself be a numeric regression.
    prior_scores = [
        round_.verdict.aggregate_score
        for round_ in rounds[:-1]
        if round_.verdict.gate_passed and round_.verdict.aggregate_score is not None
    ]
    if not prior_scores:
        return False
    best_prior_score = max(prior_scores)
    current_score = current.verdict.aggregate_score
    return not current.verdict.gate_passed or (
        current_score is not None and current_score < best_prior_score
    )


def _is_citation_slip(verdict: PanelVerdict) -> bool:
    """True when this round failed ONLY because provenance ids were wrong.

    A citation slip is cheap to fix and should not cost one of the `max_rounds`
    quality passes. A resume that is *also* rejected by another gate is not a
    slip - it needs a real revision round, and a free retry just spends tokens.

    This is the middle of three defensible policies. The strict reading would
    also require the advisory score to clear `score_threshold`, but observed
    advisory means are 51-77 against a threshold of 85, so that would almost
    never fire. The loose reading would grant a retry whenever provenance failed
    at all, which hands a weak resume a free round. Requiring a real panel score
    (`aggregate_score is not None`) keeps the retry tied to a round that actually
    produced feedback for the reviser to act on.
    """
    if verdict.gate_passed or verdict.aggregate_score is None:
        return False
    failed = {
        critique.reviewer for critique in verdict.critiques if not critique.passed
    }
    return failed == {PROVENANCE_REVIEWER}


def _best_base(rounds: list[TailorRound]) -> TailorRound:
    """The round the next revision should build on.

    Same ordering `tracking.repository.select_surfaced` uses to pick the version
    the user is shown: gate-clean first, then highest score, then latest. Always
    revising from the *last* round let a regression become the base for the next
    one, so a bad revision compounded instead of being discarded.
    """
    return max(
        rounds,
        key=lambda round_: (
            round_.verdict.gate_passed,
            round_.verdict.aggregate_score
            if round_.verdict.aggregate_score is not None
            else -1,
            round_.round_num,
        ),
    )


def run_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    match_plan_agent: Runner | None = None,
    skill_context: SkillMatchContext | None = None,
) -> list[TailorRound]:
    """Draft, then gate/review/revise until the round passes or max_rounds is hit."""
    pending: dict[str, float] = {}
    plan = None
    if config.match_plan_enabled:
        if match_plan_agent is None:
            raise ValueError("match_plan_enabled requires a match-plan agent")
        started = time.monotonic()
        plan = normalize_match_plan(
            match_plan(
                compose_match_plan_input(
                    jd_text, criteria, profile_facts, skill_context=skill_context
                ),
                match_plan_agent,
            ),
            profile_facts,
        )
        pending["match_plan"] = time.monotonic() - started
    started = time.monotonic()
    content = tailor(
        compose_tailor_input(
            jd_text, criteria, profile_facts, config.length_budget, plan
        ),
        tailor_agent,
    )
    pending["draft"] = time.monotonic() - started
    rounds: list[TailorRound] = []
    free_retries = config.provenance_retry_budget
    quality_rounds = 0
    while True:
        # Provenance is the cheap deterministic gate. It blocks the round on its
        # own, but the panel still runs: a broken citation says nothing about the
        # resume's quality, and the reviser needs both kinds of feedback to fix
        # the round in one pass rather than spending the next round rediscovering
        # what the panel would have said here.
        provenance = provenance_critique(content, profile_facts)
        started = time.monotonic()
        panel = run_panel(content, profile_facts, jd_text, config, reviewer_agents)
        pending["panel"] = time.monotonic() - started
        critiques = [provenance, *panel]
        verdict = aggregate(critiques, config)

        rounds.append(
            TailorRound(
                round_num=len(rounds) + 1,
                content=content,
                verdict=verdict,
                stage_seconds=pending,
            )
        )
        pending = {}
        # A citation slip is not a quality pass, so it does not consume one -
        # up to the configured budget.
        if _is_citation_slip(verdict) and free_retries > 0:
            free_retries -= 1
        else:
            quality_rounds += 1
        if verdict.passed or quality_rounds >= config.max_rounds:
            break
        if config.early_stop_on_regression and _has_regressed(rounds):
            break
        started = time.monotonic()
        base = _best_base(rounds)
        content = revise(
            compose_revise_input(
                base.content,
                base.verdict.critiques,
                profile_facts,
                jd_text,
                config.length_budget,
            ),
            reviser_agent,
        )
        pending["revise"] = time.monotonic() - started
    return rounds


async def arun_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    match_plan_agent: Runner | None = None,
    skill_context: SkillMatchContext | None = None,
    *,
    sem: asyncio.Semaphore,
) -> list[TailorRound]:
    """Async twin of run_tailor_review; DB writes happen after callers gather."""
    pending: dict[str, float] = {}
    plan = None
    if config.match_plan_enabled:
        if match_plan_agent is None:
            raise ValueError("match_plan_enabled requires a match-plan agent")
        started = time.monotonic()
        plan = normalize_match_plan(
            await amatch_plan(
                compose_match_plan_input(
                    jd_text, criteria, profile_facts, skill_context=skill_context
                ),
                match_plan_agent,
                sem=sem,
            ),
            profile_facts,
        )
        pending["match_plan"] = time.monotonic() - started
    started = time.monotonic()
    content = await atailor(
        compose_tailor_input(
            jd_text, criteria, profile_facts, config.length_budget, plan
        ),
        tailor_agent,
        sem=sem,
    )
    pending["draft"] = time.monotonic() - started
    rounds: list[TailorRound] = []
    free_retries = config.provenance_retry_budget
    quality_rounds = 0
    while True:
        provenance = provenance_critique(content, profile_facts)
        started = time.monotonic()
        panel = await arun_panel(
            content, profile_facts, jd_text, config, reviewer_agents, sem=sem
        )
        pending["panel"] = time.monotonic() - started
        critiques = [provenance, *panel]
        verdict = aggregate(critiques, config)

        rounds.append(
            TailorRound(
                round_num=len(rounds) + 1,
                content=content,
                verdict=verdict,
                stage_seconds=pending,
            )
        )
        pending = {}
        if _is_citation_slip(verdict) and free_retries > 0:
            free_retries -= 1
        else:
            quality_rounds += 1
        if verdict.passed or quality_rounds >= config.max_rounds:
            break
        if config.early_stop_on_regression and _has_regressed(rounds):
            break
        started = time.monotonic()
        base = _best_base(rounds)
        content = await arevise(
            compose_revise_input(
                base.content,
                base.verdict.critiques,
                profile_facts,
                jd_text,
                config.length_budget,
            ),
            reviser_agent,
            sem=sem,
        )
        pending["revise"] = time.monotonic() - started
    return rounds
