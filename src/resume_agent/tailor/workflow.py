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
from resume_agent.tailor.provenance import provenance_critique
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
    prior_clean = [round_ for round_ in rounds[:-1] if round_.verdict.gate_passed]
    if not prior_clean:
        return False
    best_prior_score = max(
        round_.verdict.aggregate_score for round_ in prior_clean
    )
    return (
        not current.verdict.gate_passed
        or current.verdict.aggregate_score < best_prior_score
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
    for round_num in range(1, config.max_rounds + 1):
        # Provenance is the cheap deterministic gate; when it fails it both blocks
        # the round and spares the expensive panel. Either way one constructor.
        provenance = provenance_critique(content, profile_facts)
        if provenance.passed:
            started = time.monotonic()
            panel = run_panel(content, profile_facts, jd_text, config, reviewer_agents)
            pending["panel"] = time.monotonic() - started
            critiques = [provenance, *panel]
        else:
            critiques = [provenance]
        verdict = aggregate(critiques, config)

        rounds.append(
            TailorRound(
                round_num=round_num,
                content=content,
                verdict=verdict,
                stage_seconds=pending,
            )
        )
        pending = {}
        if verdict.passed or round_num == config.max_rounds:
            break
        if config.early_stop_on_regression and _has_regressed(rounds):
            break
        started = time.monotonic()
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts, config.length_budget),
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
    for round_num in range(1, config.max_rounds + 1):
        provenance = provenance_critique(content, profile_facts)
        if provenance.passed:
            started = time.monotonic()
            panel = await arun_panel(
                content, profile_facts, jd_text, config, reviewer_agents, sem=sem
            )
            pending["panel"] = time.monotonic() - started
            critiques = [provenance, *panel]
        else:
            critiques = [provenance]
        verdict = aggregate(critiques, config)

        rounds.append(
            TailorRound(
                round_num=round_num,
                content=content,
                verdict=verdict,
                stage_seconds=pending,
            )
        )
        pending = {}
        if verdict.passed or round_num == config.max_rounds:
            break
        if config.early_stop_on_regression and _has_regressed(rounds):
            break
        started = time.monotonic()
        content = await arevise(
            compose_revise_input(content, verdict.critiques, profile_facts, config.length_budget),
            reviser_agent,
            sem=sem,
        )
        pending["revise"] = time.monotonic() - started
    return rounds
