import asyncio
import logging
import time
from collections.abc import Mapping

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
from resume_agent.tailor.evidence_portfolio import (
    build_evidence_catalog,
    build_fallback_portfolio,
    normalize_evidence_portfolio,
)
from resume_agent.tailor.length import format_budget
from resume_agent.tailor.numeric_evidence import numeric_evidence_critique
from resume_agent.tailor.panel import arun_panel, run_panel
from resume_agent.tailor.portfolio_alignment import portfolio_alignment_critique
from resume_agent.tailor.portfolio_planner import (
    aplan_evidence_portfolio,
    compose_evidence_portfolio_input,
    plan_evidence_portfolio,
)
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER, provenance_critique
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.skill_naming import skill_naming_critique
from resume_agent.tailor.tailoring import (
    arevise,
    atailor,
    compose_revise_input,
    compose_tailor_input,
    revise,
    tailor,
)
from resume_agent.tailor.verdict import PanelVerdict, aggregate, failing_gate_names


logger = logging.getLogger(__name__)


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict
    evidence_portfolio: EvidencePortfolio | None = None
    stage_seconds: dict[str, float] = Field(default_factory=dict)


def _deterministic_critiques(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    skill_context: SkillMatchContext | None,
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
    if (
        alignment := portfolio_alignment_critique(content, evidence_portfolio)
    ) is not None:
        critiques.append(alignment)
    return critiques


def _fallback_warning(error: Exception | None) -> str:
    reason = type(error).__name__ if error is not None else "planner unavailable"
    return f"Evidence planner unavailable ({reason}); deterministic fallback used."


def _portfolio_is_usable(portfolio: EvidencePortfolio, owner_ids: set[str]) -> bool:
    return bool(portfolio.selections) and any(
        selection.owner_id in owner_ids for selection in portfolio.selections
    )


def _plan_portfolio(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    skill_context: SkillMatchContext | None,
    agent: Runner | None,
) -> EvidencePortfolio:
    catalog = build_evidence_catalog(profile_facts, criteria, skill_context)
    if agent is not None:
        try:
            draft = plan_evidence_portfolio(
                compose_evidence_portfolio_input(
                    jd_text,
                    criteria,
                    catalog,
                    budget=format_budget(config.length_budget),
                ),
                agent,
            )
            if not _portfolio_is_usable(
                draft, {owner.owner_id for owner in catalog.owners}
            ):
                raise ValueError("planner returned no usable owner selection")
            draft = draft.model_copy(update={"status": "planned", "warning": None})
            return normalize_evidence_portfolio(
                draft,
                catalog,
                profile_facts,
                criteria,
                skill_context,
                config.length_budget,
            )
        except Exception as error:
            logger.warning(
                "evidence portfolio planner failed; using fallback", exc_info=error
            )
            warning = _fallback_warning(error)
    else:
        warning = _fallback_warning(None)
    return build_fallback_portfolio(
        catalog,
        profile_facts,
        criteria,
        skill_context,
        config.length_budget,
        warning=warning,
    )


async def _aplan_portfolio(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    skill_context: SkillMatchContext | None,
    agent: Runner | None,
    *,
    sem: asyncio.Semaphore,
) -> EvidencePortfolio:
    catalog = build_evidence_catalog(profile_facts, criteria, skill_context)
    if agent is not None:
        try:
            draft = await aplan_evidence_portfolio(
                compose_evidence_portfolio_input(
                    jd_text,
                    criteria,
                    catalog,
                    budget=format_budget(config.length_budget),
                ),
                agent,
                sem=sem,
            )
            if not _portfolio_is_usable(
                draft, {owner.owner_id for owner in catalog.owners}
            ):
                raise ValueError("planner returned no usable owner selection")
            draft = draft.model_copy(update={"status": "planned", "warning": None})
            return normalize_evidence_portfolio(
                draft,
                catalog,
                profile_facts,
                criteria,
                skill_context,
                config.length_budget,
            )
        except Exception as error:
            logger.warning(
                "evidence portfolio planner failed; using fallback", exc_info=error
            )
            warning = _fallback_warning(error)
    else:
        warning = _fallback_warning(None)
    return build_fallback_portfolio(
        catalog,
        profile_facts,
        criteria,
        skill_context,
        config.length_budget,
        warning=warning,
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
        portfolio = _plan_portfolio(
            jd_text,
            criteria,
            profile_facts,
            config,
            skill_context,
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
    rounds: list[TailorRound] = []
    free_retries = config.provenance_retry_budget
    quality_rounds = 0
    while True:
        deterministic = _deterministic_critiques(
            content, profile_facts, skill_context, portfolio
        )
        started = time.monotonic()
        panel = run_panel(
            content,
            profile_facts,
            jd_text,
            config,
            reviewer_agents,
            coverage=coverage,
        )
        pending["panel"] = time.monotonic() - started
        critiques = [*deterministic, *panel]
        verdict = aggregate(critiques, config)

        rounds.append(
            TailorRound(
                round_num=len(rounds) + 1,
                content=content,
                verdict=verdict,
                evidence_portfolio=portfolio,
                stage_seconds=pending,
            )
        )
        pending = {}
        # A citation slip is not a quality pass, so it does not consume one -
        # up to the configured budget.
        if _is_citation_slip(verdict, config) and free_retries > 0:
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
                coverage,
                portfolio,
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
    evidence_portfolio_agent: Runner | None = None,
) -> list[TailorRound]:
    """Async twin of run_tailor_review; DB writes happen after callers gather."""
    pending: dict[str, float] = {}
    portfolio = None
    if config.portfolio_enabled:
        started = time.monotonic()
        portfolio = await _aplan_portfolio(
            jd_text,
            criteria,
            profile_facts,
            config,
            skill_context,
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
    rounds: list[TailorRound] = []
    free_retries = config.provenance_retry_budget
    quality_rounds = 0
    while True:
        deterministic = _deterministic_critiques(
            content, profile_facts, skill_context, portfolio
        )
        started = time.monotonic()
        panel = await arun_panel(
            content,
            profile_facts,
            jd_text,
            config,
            reviewer_agents,
            sem=sem,
            coverage=coverage,
        )
        pending["panel"] = time.monotonic() - started
        critiques = [*deterministic, *panel]
        verdict = aggregate(critiques, config)

        rounds.append(
            TailorRound(
                round_num=len(rounds) + 1,
                content=content,
                verdict=verdict,
                evidence_portfolio=portfolio,
                stage_seconds=pending,
            )
        )
        pending = {}
        if _is_citation_slip(verdict, config) and free_retries > 0:
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
                coverage,
                portfolio,
            ),
            reviser_agent,
            sem=sem,
        )
        pending["revise"] = time.monotonic() - started
    return rounds
