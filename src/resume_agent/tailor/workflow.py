import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import Field

from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.evidence_portfolio import EvidencePortfolio
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.profile.matrix import SkillMatchContext
from resume_agent.tailor.coverage import coverage_critique, format_coverage
from resume_agent.tailor.depth import depth_critique
from resume_agent.tailor.evidence_portfolio import (
    PortfolioPlanRequest,
    aplan_portfolio,
    plan_portfolio,
)
from resume_agent.tailor.numeric_evidence import numeric_evidence_critique
from resume_agent.tailor.panel import arun_panel, run_panel
from resume_agent.tailor.portfolio_alignment import portfolio_alignment_critique
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER, provenance_critique
from resume_agent.tailor.review_config import LengthBudget, ReviewConfig
from resume_agent.tailor.skill_naming import skill_naming_critique
from resume_agent.tailor.tailoring import (
    RevisionRoundContext,
    arevise,
    atailor,
    compose_revise_input,
    compose_tailor_input,
    revise,
    tailor,
)
from resume_agent.tailor.verdict import PanelVerdict, aggregate, failing_gate_names


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict
    evidence_portfolio: EvidencePortfolio | None = None
    stage_seconds: dict[str, float] = Field(default_factory=dict)


@dataclass(frozen=True)
class TailorRequest:
    jd_text: str
    criteria: JobCriteria
    profile_facts: ProfileFacts
    config: ReviewConfig
    skill_context: SkillMatchContext | None = None


@dataclass(frozen=True)
class TailorAgents:
    writer: Runner
    reviewers: Mapping[str, Runner]
    reviser: Runner
    portfolio_planner: Runner | None = None


@dataclass
class _WorkflowState:
    """Execution-independent Tailoring round policy."""

    request: TailorRequest
    content: ResumeContent
    coverage: str
    portfolio: EvidencePortfolio | None
    pending: dict[str, float]
    rounds: list[TailorRound]
    free_retries: int
    quality_rounds: int = 0

    def record(self, panel: list[ReviewCritique]) -> PanelVerdict:
        deterministic = _deterministic_critiques(
            self.content,
            self.request.profile_facts,
            self.request.skill_context,
            self.request.config.length_budget,
            self.portfolio,
        )
        verdict = aggregate([*deterministic, *panel], self.request.config)
        self.rounds.append(
            TailorRound(
                round_num=len(self.rounds) + 1,
                content=self.content,
                verdict=verdict,
                evidence_portfolio=self.portfolio,
                stage_seconds=self.pending,
            )
        )
        self.pending = {}
        if _is_citation_slip(verdict, self.request.config) and self.free_retries > 0:
            self.free_retries -= 1
        else:
            self.quality_rounds += 1
        return verdict

    def should_stop(self, verdict: PanelVerdict) -> bool:
        return (
            verdict.passed
            or self.quality_rounds >= self.request.config.max_rounds
            or (
                self.request.config.early_stop_on_regression
                and _has_regressed(self.rounds)
            )
        )

    def next_revision_input(self) -> str:
        return _compose_next_revision_input(
            self.rounds,
            self.request.profile_facts,
            self.request.jd_text,
            self.request.config,
            self.coverage,
            self.portfolio,
        )


def _deterministic_critiques(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    skill_context: SkillMatchContext | None,
    budget: LengthBudget,
    evidence_portfolio: EvidencePortfolio | None = None,
) -> list[ReviewCritique]:
    """Every in-process critique for one round, gates first.

    The gates run before the panel because each is mechanically provable: their
    issues reach the reviser in the round they were detected rather than costing
    a premium fact-check round to rediscover.

    Coverage rides along last and is advisory, never a gate. The runtime marker
    keeps it out of gate and weighted-review selection, while a configured
    reviewer with the same name remains valid and authoritative. It carries the
    coverage rate for `tailor_health`.
    """
    critiques: list[ReviewCritique] = [
        provenance_critique(content, profile_facts),
        skill_naming_critique(content, profile_facts),
        numeric_evidence_critique(content, profile_facts),
    ]
    if (coverage := coverage_critique(content, skill_context)) is not None:
        critiques.append(coverage)
    if (depth := depth_critique(content, profile_facts, budget)) is not None:
        critiques.append(depth)
    if (
        alignment := portfolio_alignment_critique(content, evidence_portfolio)
    ) is not None:
        critiques.append(alignment)
    return critiques


def _portfolio_request(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    skill_context: SkillMatchContext | None,
) -> PortfolioPlanRequest:
    return PortfolioPlanRequest(
        jd_text=jd_text,
        criteria=criteria,
        profile_facts=profile_facts,
        skill_context=skill_context,
        budget=config.length_budget,
    )


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


def _is_citation_slip(verdict: PanelVerdict, config: ReviewConfig) -> bool:
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

    Only *gate* failures count against the slip: `aggregate()` deliberately
    ignores an advisory reviewer's `passed` flag and scores it against
    `score_threshold` instead, so a failing advisory verdict is not grounds to
    deny the free retry.
    """
    if verdict.gate_passed or verdict.aggregate_score is None:
        return False
    config_gates = {r.name for r in config.reviewers if r.gate}
    failed = set(failing_gate_names(verdict.critiques, config_gates))
    return failed == {PROVENANCE_REVIEWER}


def _best_base(rounds: list[TailorRound]) -> TailorRound:
    """The round the next revision should build on.

    Same policy `tracking.repository.select_surfaced` uses to pick the version
    the user is shown: best-scoring gate-clean round, falling back to the
    latest round when none is clean. Always revising from the *last* round let
    a regression become the base for the next one, so a bad revision compounded
    instead of being discarded; picking the highest-scoring round even when it
    was never gate-clean could revise from a round whose citations were never
    fixed, discarding a later round that already repaired them.
    """
    clean = [round_ for round_ in rounds if round_.verdict.gate_passed]
    if not clean:
        return max(rounds, key=lambda round_: round_.round_num)
    return max(
        clean,
        key=lambda round_: (
            round_.verdict.aggregate_score
            if round_.verdict.aggregate_score is not None
            else -1,
            round_.round_num,
        ),
    )


def _compose_next_revision_input(
    rounds: list[TailorRound],
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    coverage: str,
    portfolio: EvidencePortfolio | None,
) -> str:
    """Build from the safest round while acting on the latest round's verdict."""
    latest = rounds[-1]
    base = _best_base(rounds)
    config_gates = {reviewer.name for reviewer in config.reviewers if reviewer.gate}
    failed_gates = tuple(failing_gate_names(latest.verdict.critiques, config_gates))
    return compose_revise_input(
        base.content,
        latest.verdict.critiques,
        profile_facts,
        jd_text,
        config.length_budget,
        coverage,
        portfolio,
        round_context=RevisionRoundContext(
            base_round_num=base.round_num,
            feedback_round_num=latest.round_num,
            reviewed_content=latest.content,
            passed=latest.verdict.passed,
            gate_passed=latest.verdict.gate_passed,
            aggregate_score=latest.verdict.aggregate_score,
            failed_gates=failed_gates,
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
    evidence_portfolio_agent: Runner | None = None,
) -> list[TailorRound]:
    """Draft, then gate/review/revise until the round passes or max_rounds is hit."""
    pending: dict[str, float] = {}
    portfolio = None
    if config.portfolio_enabled:
        started = time.monotonic()
        portfolio = plan_portfolio(
            _portfolio_request(jd_text, criteria, profile_facts, config, skill_context),
            evidence_portfolio_agent or match_plan_agent,
        )
        pending["evidence_portfolio"] = time.monotonic() - started
    coverage = format_coverage(skill_context)
    started = time.monotonic()
    content = tailor(
        compose_tailor_input(
            jd_text,
            criteria,
            profile_facts,
            config.length_budget,
            coverage=coverage,
            evidence_portfolio=portfolio,
        ),
        tailor_agent,
    )
    pending["draft"] = time.monotonic() - started
    state = _WorkflowState(
        request=TailorRequest(jd_text, criteria, profile_facts, config, skill_context),
        content=content,
        coverage=coverage,
        portfolio=portfolio,
        pending=pending,
        rounds=[],
        free_retries=config.provenance_retry_budget,
    )
    while True:
        started = time.monotonic()
        panel = run_panel(
            state.content,
            profile_facts,
            jd_text,
            config,
            reviewer_agents,
            coverage=coverage,
        )
        state.pending["panel"] = time.monotonic() - started
        verdict = state.record(panel)
        if state.should_stop(verdict):
            break
        started = time.monotonic()
        state.content = revise(
            state.next_revision_input(),
            reviser_agent,
        )
        state.pending["revise"] = time.monotonic() - started
    return state.rounds


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
    evidence_portfolio_agent: Runner | None = None,
) -> list[TailorRound]:
    """Async twin of run_tailor_review; DB writes happen after callers gather."""
    pending: dict[str, float] = {}
    portfolio = None
    if config.portfolio_enabled:
        started = time.monotonic()
        portfolio = await aplan_portfolio(
            _portfolio_request(jd_text, criteria, profile_facts, config, skill_context),
            evidence_portfolio_agent or match_plan_agent,
            sem=sem,
        )
        pending["evidence_portfolio"] = time.monotonic() - started
    coverage = format_coverage(skill_context)
    started = time.monotonic()
    content = await atailor(
        compose_tailor_input(
            jd_text,
            criteria,
            profile_facts,
            config.length_budget,
            coverage=coverage,
            evidence_portfolio=portfolio,
        ),
        tailor_agent,
        sem=sem,
    )
    pending["draft"] = time.monotonic() - started
    state = _WorkflowState(
        request=TailorRequest(jd_text, criteria, profile_facts, config, skill_context),
        content=content,
        coverage=coverage,
        portfolio=portfolio,
        pending=pending,
        rounds=[],
        free_retries=config.provenance_retry_budget,
    )
    while True:
        started = time.monotonic()
        panel = await arun_panel(
            state.content,
            profile_facts,
            jd_text,
            config,
            reviewer_agents,
            sem=sem,
            coverage=coverage,
        )
        state.pending["panel"] = time.monotonic() - started
        verdict = state.record(panel)
        if state.should_stop(verdict):
            break
        started = time.monotonic()
        state.content = await arevise(
            state.next_revision_input(),
            reviser_agent,
            sem=sem,
        )
        state.pending["revise"] = time.monotonic() - started
    return state.rounds


class TailorWorkflow:
    """Deep Tailoring module with compatibility adapters at the old interface."""

    def run(self, request: TailorRequest, agents: TailorAgents) -> list[TailorRound]:
        return run_tailor_review(
            request.jd_text,
            request.criteria,
            request.profile_facts,
            request.config,
            agents.writer,
            agents.reviewers,
            agents.reviser,
            skill_context=request.skill_context,
            evidence_portfolio_agent=agents.portfolio_planner,
        )

    async def arun(
        self,
        request: TailorRequest,
        agents: TailorAgents,
        *,
        sem: asyncio.Semaphore,
    ) -> list[TailorRound]:
        return await arun_tailor_review(
            request.jd_text,
            request.criteria,
            request.profile_facts,
            request.config,
            agents.writer,
            agents.reviewers,
            agents.reviser,
            skill_context=request.skill_context,
            sem=sem,
            evidence_portfolio_agent=agents.portfolio_planner,
        )
