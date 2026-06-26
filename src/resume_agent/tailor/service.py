import asyncio
from collections.abc import Mapping, Sequence

from sqlmodel import Session

from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.progress import ProgressReporter
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import TailorRound, arun_tailor_review
from resume_agent.tracking.repository import save_job, save_resume_version
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def _persist_rounds(
    session: Session, job: Job, rounds: list[TailorRound]
) -> list[ResumeVersion]:
    """Persist each review round as a ResumeVersion and mark the job tailored."""
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    versions: list[ResumeVersion] = []
    for r in rounds:
        version = ResumeVersion(
            job_id=job.id,
            round=r.round_num,
            content_json=r.content.model_dump(mode="json"),
            review_score=r.verdict.aggregate_score,
            fact_check_passed=r.verdict.gate_passed,
            critique_json=[c.model_dump(mode="json") for c in r.verdict.critiques],
        )
        versions.append(save_resume_version(session, version))
    job.status = JobStatus.tailored.value
    save_job(session, job)
    return versions


def tailor_job(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
) -> list[ResumeVersion]:
    """Run the loop for one job and persist each round. Marks the job tailored."""
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    sem = asyncio.Semaphore(get_settings().llm_concurrency)
    rounds = asyncio.run(
        arun_tailor_review(
            job.jd_text,
            criteria,
            profile_facts,
            config,
            tailor_agent,
            reviewer_agents,
            reviser_agent,
            sem=sem,
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

        rounds_results = asyncio.run(
            gather_isolated(
                list(targets),
                lambda job: arun_tailor_review(
                    job.jd_text,
                    _criteria(job),
                    profile_facts,
                    config,
                    tailor_agent,
                    reviewer_agents,
                    reviser_agent,
                    sem=sem,
                ),
                on_complete=on_complete,
                checkpoint=reporter.checkpoint if reporter else None,
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
