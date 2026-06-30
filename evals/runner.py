from dataclasses import dataclass

from evals.judge import JudgeVerdict, compose_judge_input, validate_judge_verdict
from evals.metrics import (
    ProbeRecord,
    RoundRecord,
    budget_ok,
    must_cite_covered,
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
from resume_agent.services.agents import TailorBundle
from resume_agent.tailor.panel import compose_evidence_review_input, review_one
from resume_agent.tailor.provenance import resolve_evidence
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import run_tailor_review


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
    raise ValueError(
        f"{trap.id}: probe_provenance must reference an Experience Bullet"
    )


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
    )
    if live_criteria or case.criteria is None:
        if extract_agent is None:
            raise ValueError("an extract_agent is required for live or missing criteria")
        criteria = extract_job_criteria(
            case.jd_text, MeteredRunner(extract_agent, usage)
        )
    else:
        criteria = case.criteria

    tailor_rounds = run_tailor_review(
        jd_text=case.jd_text,
        criteria=criteria,
        profile_facts=profile,
        config=config,
        tailor_agent=metered_bundle.tailor,
        reviewer_agents=metered_bundle.reviewers,
        reviser_agent=metered_bundle.reviser,
    )
    scored_reviewers = {
        spec.name
        for spec in config.reviewers
        if not spec.gate and spec.weight > 0
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
        )
        for round_ in tailor_rounds
    ]
    final = rounds[-1].content

    fact_check = metered_bundle.reviewers.get("fact-check")
    if case.traps and fact_check is None:
        raise ValueError("trap probes require the configured fact-check reviewer")
    probes: list[ProbeRecord] = []
    for trap in case.traps:
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
                        issue.severity == Severity.blocking
                        for issue in critique.issues
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

    verdict = MeteredRunner(judge_agent, usage).run(
        compose_judge_input(final, case.jd_text, case.rubric)
    ).content
    if not isinstance(verdict, JudgeVerdict):
        raise TypeError(
            f"Expected JudgeVerdict from judge, got {type(verdict).__name__}"
        )
    validate_judge_verdict(verdict, case.rubric)
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
    )
