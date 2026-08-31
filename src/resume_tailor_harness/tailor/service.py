import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from sqlmodel import Session

from resume_tailor_harness.concurrency import gather_isolated
from resume_tailor_harness.config import get_settings
from resume_tailor_harness.career_skills.provenance import append_skill_use
from resume_tailor_harness.llm_runner import Runner, run_with_cleanup
from resume_tailor_harness.models.job import JobCriteria
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.profile.matrix import (
    SkillMatchContext,
    SkillMatrix,
    build_skill_match_context,
)
from resume_tailor_harness.progress import ProgressReporter
from resume_tailor_harness.services.errors import StageFailure
from resume_tailor_harness.tailor.review_config import ReviewConfig
from resume_tailor_harness.tailor.workflow import (
    TailorAgents,
    TailorRequest,
    TailorRound,
    TailorWorkflow,
)
from resume_tailor_harness.taxonomy.clusters import ClusterMap
from resume_tailor_harness.taxonomy.snapshot import EffectiveTaxonomy
from resume_tailor_harness.tracking.repository import (
    resume_versions_for_job,
    save_job,
    save_resume_version,
)
from resume_tailor_harness.tracking.stages import advance
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TailorOutcome:
    """What one tailor run produced, per job, including what went wrong."""

    versions: dict[int, list[ResumeVersion]] = field(default_factory=dict)
    failures: dict[int, StageFailure] = field(default_factory=dict)
    model: str | None = None


def _next_attempt(session: Session, job_id: int) -> int:
    existing = resume_versions_for_job(session, job_id)
    return max((version.attempt for version in existing), default=0) + 1


def _persist_rounds(
    session: Session,
    job: Job,
    rounds: list[TailorRound],
    config: ReviewConfig,
    *,
    model: str | None = None,
    tailor_agent: Runner | None = None,
    reviser_agent: Runner | None = None,
    reviewer_agents: Mapping[str, Runner] | None = None,
    taxonomy: EffectiveTaxonomy | None = None,
) -> list[ResumeVersion]:
    """Persist each review round as a ResumeVersion and mark the job tailored.

    Status moves forward only: re-tailoring a rendered job leaves it rendered.
    Versions are appended under a fresh attempt number; nothing is replaced.
    """
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    attempt = _next_attempt(session, job.id)
    # Recorded once per call, not per round: every round in a single tailor run
    # shares the same ReviewConfig, and this is what read-side callers (job
    # detail, resume render) use instead of the CURRENT review config so a
    # settings change after the fact doesn't relabel a round's own gates.
    gate_reviewers = sorted(r.name for r in config.reviewers if r.gate)
    versions: list[ResumeVersion] = []
    for r in rounds:
        version = ResumeVersion(
            job_id=job.id,
            round=r.round_num,
            attempt=attempt,
            tailor_model=model,
            content_json=r.content.model_dump(mode="json"),
            review_score=r.verdict.aggregate_score,
            fact_check_passed=r.verdict.gate_passed,
            critique_json=[c.model_dump(mode="json") for c in r.verdict.critiques],
            evidence_portfolio_json=(
                r.evidence_portfolio.model_dump(mode="json")
                if r.evidence_portfolio is not None
                else None
            ),
            evidence_portfolio_status=(
                r.evidence_portfolio.status
                if r.evidence_portfolio is not None
                else None
            ),
            gate_reviewers_json=gate_reviewers,
            taxonomy_revision=(
                taxonomy.semantic_revision if taxonomy is not None else None
            ),
            taxonomy_manifest_json=(
                asdict(taxonomy.manifest) if taxonomy is not None else None
            ),
        )
        raw_uses: object = None
        if (
            tailor_agent is not None
            and "draft" in r.stage_seconds
            and getattr(tailor_agent, "run_meta", None) is not None
        ):
            raw_uses = append_skill_use(raw_uses, tailor_agent, "generated")
        if (
            reviser_agent is not None
            and "revise" in r.stage_seconds
            and getattr(reviser_agent, "run_meta", None) is not None
        ):
            raw_uses = append_skill_use(raw_uses, reviser_agent, "revised")
        for reviewer in (reviewer_agents or {}).values():
            if getattr(reviewer, "run_meta", None) is not None:
                raw_uses = append_skill_use(raw_uses, reviewer, "reviewed")
        if raw_uses:
            version.skill_uses_json = raw_uses
        versions.append(save_resume_version(session, version))
    advance(job, JobStatus.tailored.value, never_regress=True)
    save_job(session, job)
    logger.info(
        "tailor job=%s attempt=%s rounds=%s total_llm_seconds=%.1f stages=%s",
        job.id,
        attempt,
        len(rounds),
        sum(sum(round_.stage_seconds.values()) for round_ in rounds),
        [round_.stage_seconds for round_ in rounds],
    )
    return versions


def tailor_job(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    match_plan_agent: Runner | None = None,
    skill_context: SkillMatchContext | None = None,
    evidence_portfolio_agent: Runner | None = None,
    taxonomy: EffectiveTaxonomy | None = None,
) -> list[ResumeVersion]:
    """Run the loop for one job and persist each round. Marks the job tailored."""
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    sem = asyncio.Semaphore(get_settings().llm_concurrency)
    runners = (tailor_agent, *reviewer_agents.values(), reviser_agent)
    planner = evidence_portfolio_agent or match_plan_agent
    if planner is not None:
        runners = (*runners, planner)
    rounds = asyncio.run(
        run_with_cleanup(
            TailorWorkflow().arun(
                TailorRequest(
                    job.jd_text, criteria, profile_facts, config, skill_context
                ),
                TailorAgents(tailor_agent, reviewer_agents, reviser_agent, planner),
                sem=sem,
            ),
            *runners,
        )
    )
    return _persist_rounds(
        session,
        job,
        rounds,
        config,
        tailor_agent=tailor_agent,
        reviser_agent=reviser_agent,
        reviewer_agents=reviewer_agents,
        taxonomy=taxonomy,
    )


def tailor_jobs(
    session: Session,
    targets: Sequence[Job],
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    reporter: ProgressReporter | None = None,
    match_plan_agent: Runner | None = None,
    skill_matrix: SkillMatrix | None = None,
    cluster_map: ClusterMap | None = None,
    model: str | None = None,
    evidence_portfolio_agent: Runner | None = None,
    taxonomy: EffectiveTaxonomy | None = None,
) -> TailorOutcome:
    """Tailor targets concurrently, then persist successful jobs serially."""
    for job in targets:
        if job.id is None:
            raise ValueError("Cannot tailor a job that has not been persisted")
    if reporter:
        reporter.begin(len(targets), "Tailoring")
    results: dict[int, list[ResumeVersion]] = {}
    failures: dict[int, StageFailure] = {}
    planner = evidence_portfolio_agent or match_plan_agent
    if targets:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(n)) if reporter else None

        def _criteria(job: Job) -> JobCriteria:
            return JobCriteria.model_validate(job.criteria_json or {})

        def _skill_context(criteria: JobCriteria) -> SkillMatchContext | None:
            if skill_matrix is None or cluster_map is None:
                return None
            return build_skill_match_context(criteria, skill_matrix, cluster_map)

        async def _run_job(job: Job) -> list[TailorRound]:
            criteria = _criteria(job)
            return await TailorWorkflow().arun(
                TailorRequest(
                    job.jd_text,
                    criteria,
                    profile_facts,
                    config,
                    _skill_context(criteria),
                ),
                TailorAgents(tailor_agent, reviewer_agents, reviser_agent, planner),
                sem=sem,
            )

        runners = (tailor_agent, *reviewer_agents.values(), reviser_agent)
        if planner is not None:
            runners = (*runners, planner)
        rounds_results = asyncio.run(
            run_with_cleanup(
                gather_isolated(
                    list(targets),
                    _run_job,
                    on_complete=on_complete,
                    checkpoint=reporter.checkpoint if reporter else None,
                ),
                *runners,
            )
        )
        for job, res in zip(targets, rounds_results):
            job_id = job.id
            if job_id is None:
                raise ValueError("Cannot tailor a job that has not been persisted")
            if not res.ok or res.value is None:
                # Previously a bare `continue`: the captured exception was
                # discarded, so callers could only report a count. Log it and
                # hand it back so the cause reaches the user.
                error = res.error or RuntimeError("tailoring produced no rounds")
                logger.warning("tailor job=%s failed", job_id, exc_info=error)
                failures[job_id] = StageFailure.from_exception(error)
                continue
            results[job_id] = _persist_rounds(
                session,
                job,
                res.value,
                config,
                model=model,
                tailor_agent=tailor_agent,
                reviser_agent=reviser_agent,
                reviewer_agents=reviewer_agents,
                taxonomy=taxonomy,
            )
    if reporter:
        reporter.done()
    return TailorOutcome(versions=results, failures=failures, model=model)
