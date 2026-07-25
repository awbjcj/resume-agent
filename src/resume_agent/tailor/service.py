import asyncio
import logging
from collections.abc import Mapping, Sequence

from sqlmodel import Session

from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner, run_with_cleanup
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.matrix import (
    SkillMatchContext,
    SkillMatrix,
    build_skill_match_context,
)
from resume_agent.progress import ProgressReporter
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import TailorRound, arun_tailor_review
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.tracking.repository import (
    resume_versions_for_job,
    save_job,
    save_resume_version,
)
from resume_agent.tracking.stages import advance
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion

logger = logging.getLogger(__name__)


def _next_attempt(session: Session, job_id: int) -> int:
    existing = resume_versions_for_job(session, job_id)
    return max((version.attempt for version in existing), default=0) + 1


def _persist_rounds(
    session: Session,
    job: Job,
    rounds: list[TailorRound],
    *,
    model: str | None = None,
) -> list[ResumeVersion]:
    """Persist each review round as a ResumeVersion and mark the job tailored.

    Status moves forward only: re-tailoring a rendered job leaves it rendered.
    Versions are appended under a fresh attempt number; nothing is replaced.
    """
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    attempt = _next_attempt(session, job.id)
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
        )
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
) -> list[ResumeVersion]:
    """Run the loop for one job and persist each round. Marks the job tailored."""
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    sem = asyncio.Semaphore(get_settings().llm_concurrency)
    runners = (tailor_agent, *reviewer_agents.values(), reviser_agent)
    if match_plan_agent is not None:
        runners = (*runners, match_plan_agent)
    rounds = asyncio.run(
        run_with_cleanup(
            arun_tailor_review(
                job.jd_text,
                criteria,
                profile_facts,
                config,
                tailor_agent,
                reviewer_agents,
                reviser_agent,
                match_plan_agent,
                skill_context=skill_context,
                sem=sem,
            ),
            *runners,
        )
    )
    return _persist_rounds(session, job, rounds)


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
) -> dict[int, list[ResumeVersion]]:
    """Tailor targets concurrently, then persist successful jobs serially."""
    for job in targets:
        if job.id is None:
            raise ValueError("Cannot tailor a job that has not been persisted")
    if reporter:
        reporter.begin(len(targets), "Tailoring")
    results: dict[int, list[ResumeVersion]] = {}
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
            return await arun_tailor_review(
                job.jd_text,
                criteria,
                profile_facts,
                config,
                tailor_agent,
                reviewer_agents,
                reviser_agent,
                match_plan_agent,
                skill_context=_skill_context(criteria),
                sem=sem,
            )

        runners = (tailor_agent, *reviewer_agents.values(), reviser_agent)
        if match_plan_agent is not None:
            runners = (*runners, match_plan_agent)
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
            if not res.ok or res.value is None:
                continue
            job_id = job.id
            if job_id is None:
                raise ValueError("Cannot tailor a job that has not been persisted")
            results[job_id] = _persist_rounds(session, job, res.value)
    if reporter:
        reporter.done()
    return results
