from dataclasses import dataclass, field
from pathlib import Path

from evals.judge import JudgeVerdict, compose_judge_input, validate_judge_verdict
from evals.metrics import (
    ProbeRecord,
    RoundRecord,
    budget_ok,
    must_cite_covered,
    portfolio_forbidden_hits,
    portfolio_mandatory_hits,
    provenance_ok,
    trap_avoided,
)
from evals.schema import EvalCase, Trap
from evals.usage import MeteredRunner, UsageCollector, UsageTotals
from resume_agent.discovery.extract import extract_job_criteria
from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_agent.models.review import Severity
from resume_agent.profile.matrix import (
    Overrides,
    build_matrix,
    build_skill_match_context,
)
from resume_agent.services.agents import TailorBundle
from resume_agent.taxonomy.clusters import load_cluster_map
from resume_agent.tailor.panel import compose_evidence_review_input, review_one
from resume_agent.tailor.provenance import resolve_evidence
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import TailorRound, run_tailor_review
from resume_agent.tracking.repository import select_surfaced


@dataclass
class CaseResult:
    case_id: str
    jd_text: str
    criteria: JobCriteria
    rubric: list[str]
    traps: list[Trap]
    rounds: list[RoundRecord]
    trap_avoided: bool
    provenance_ok: bool
    must_cite_covered: bool
    budget_ok: bool
    judge: JudgeVerdict
    final_quality: int
    probes: list[ProbeRecord]
    usage: UsageTotals
    surfaced_round_num: int | None = None
    needs_attention: bool = False
    regressed: bool = False
    portfolio_status: str | None = None
    portfolio_mandatory_hits: int = 0
    portfolio_mandatory_total: int = 0
    portfolio_forbidden_hits: list[str] = field(default_factory=list)


def _surface_round(
    tailor_rounds: list[TailorRound],
) -> tuple[TailorRound, bool, bool]:
    """Mirror the product read-side selector for non-persisted eval rounds."""
    surfaced, no_clean_round, regressed = select_surfaced(
        tailor_rounds,
        is_clean=lambda round_: round_.verdict.gate_passed,
        score_key=lambda round_: (round_.verdict.aggregate_score, round_.round_num),
        latest_key=lambda round_: round_.round_num,
    )
    assert surfaced is not None  # run_case always supplies at least one round
    return surfaced, no_clean_round, regressed


def build_probe_resume(trap: Trap, profile: ProfileFacts) -> ResumeContent:
    for experience in profile.experience:
        for bullet in experience.bullets:
            if bullet.id == trap.probe_provenance:
                return ResumeContent(
                    contact=profile.contact,
                    experience=[
                        TailoredExperience(
                            company=experience.company,
                            title=experience.title,
                            location=experience.location,
                            start=experience.start,
                            end=experience.end,
                            provenance=experience.id,
                            bullets=[
                                TailoredBullet(
                                    text=trap.probe_claim,
                                    provenance=bullet.id,
                                )
                            ],
                        )
                    ],
                )
    raise ValueError(f"{trap.id}: probe_provenance must reference an Experience Bullet")


def run_case(
    case: EvalCase,
    profile: ProfileFacts,
    config: ReviewConfig,
    bundle: TailorBundle,
    judge_agent: Runner,
    *,
    extract_agent: Runner | None = None,
    live_criteria: bool = False,
) -> CaseResult:
    usage = UsageCollector()
    metered_bundle = TailorBundle(
        tailor=MeteredRunner(bundle.tailor, usage),
        reviser=MeteredRunner(bundle.reviser, usage),
        reviewers={
            name: MeteredRunner(agent, usage)
            for name, agent in bundle.reviewers.items()
        },
        revision=MeteredRunner(bundle.revision, usage),
        match_plan=None,
        evidence_portfolio=None,
    )
    planner = bundle.evidence_portfolio
    if planner is None:
        planner = bundle.match_plan
    if planner is not None:
        metered_planner = MeteredRunner(planner, usage)
        metered_bundle.match_plan = metered_planner
        metered_bundle.evidence_portfolio = metered_planner
    if live_criteria or case.criteria is None:
        if extract_agent is None:
            raise ValueError(
                "an extract_agent is required for live or missing criteria"
            )
        criteria = extract_job_criteria(
            case.jd_text, MeteredRunner(extract_agent, usage)
        )
    else:
        criteria = case.criteria

    skill_context = None
    if config.portfolio_enabled:
        cluster_map = load_cluster_map(Path("evals/portfolio_cluster_map.json"))
        matrix = build_matrix(profile, cluster_map, Overrides())
        skill_context = build_skill_match_context(criteria, matrix, cluster_map)

    tailor_rounds = run_tailor_review(
        jd_text=case.jd_text,
        criteria=criteria,
        profile_facts=profile,
        config=config,
        tailor_agent=metered_bundle.tailor,
        reviewer_agents=metered_bundle.reviewers,
        reviser_agent=metered_bundle.reviser,
        evidence_portfolio_agent=metered_bundle.evidence_portfolio,
        skill_context=skill_context,
    )
    scored_reviewers = {
        spec.name for spec in config.reviewers if not spec.gate and spec.weight > 0
    }
    rounds = [
        RoundRecord(
            round_num=round_.round_num,
            content=round_.content,
            aggregate_score=(
                round_.verdict.aggregate_score
                if any(
                    critique.reviewer in scored_reviewers
                    for critique in round_.verdict.critiques
                )
                else None
            ),
            critiques=round_.verdict.critiques,
            phase_seconds=round_.stage_seconds,
        )
        for round_ in tailor_rounds
    ]
    surfaced, needs_attention, regressed = _surface_round(tailor_rounds)
    final = surfaced.content

    fact_check = metered_bundle.reviewers.get("fact-check")
    if case.traps and fact_check is None:
        raise ValueError("trap probes require the configured fact-check reviewer")
    probes: list[ProbeRecord] = []
    for trap in case.traps:
        assert fact_check is not None  # guaranteed above when case.traps is non-empty
        probe = build_probe_resume(trap, profile)
        try:
            critique = review_one(
                compose_evidence_review_input(
                    probe,
                    case.jd_text,
                    resolve_evidence(probe, profile),
                ),
                fact_check,
            )
            probes.append(
                ProbeRecord(
                    trap_id=trap.id,
                    detected=any(
                        issue.severity == Severity.blocking for issue in critique.issues
                    ),
                )
            )
        except Exception as exc:
            probes.append(
                ProbeRecord(
                    trap_id=trap.id,
                    detected=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    verdict = (
        MeteredRunner(judge_agent, usage)
        .run(compose_judge_input(final, case.jd_text, case.rubric))
        .content
    )
    if not isinstance(verdict, JudgeVerdict):
        raise TypeError(
            f"Expected JudgeVerdict from judge, got {type(verdict).__name__}"
        )
    validate_judge_verdict(verdict, case.rubric)
    portfolio = surfaced.evidence_portfolio
    expectation = case.portfolio_expectation
    mandatory_hits, mandatory_total = portfolio_mandatory_hits(
        portfolio,
        expectation.mandatory_evidence_ids if expectation else [],
    )
    forbidden_hits = portfolio_forbidden_hits(
        portfolio,
        expectation.forbidden_evidence_ids if expectation else [],
        expectation.forbidden_highlight_terms if expectation else [],
    )
    return CaseResult(
        case_id=case.id,
        jd_text=case.jd_text,
        criteria=criteria,
        rubric=case.rubric,
        traps=case.traps,
        rounds=rounds,
        trap_avoided=trap_avoided(final, case.traps),
        provenance_ok=provenance_ok(final, profile),
        must_cite_covered=must_cite_covered(final, case.must_cite),
        budget_ok=budget_ok(final, config.length_budget),
        judge=verdict,
        final_quality=verdict.output_quality,
        probes=probes,
        usage=usage.snapshot(),
        surfaced_round_num=surfaced.round_num,
        needs_attention=needs_attention,
        regressed=regressed,
        portfolio_status=portfolio.status if portfolio is not None else None,
        portfolio_mandatory_hits=mandatory_hits,
        portfolio_mandatory_total=mandatory_total,
        portfolio_forbidden_hits=forbidden_hits,
    )
