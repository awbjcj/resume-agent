from collections.abc import Mapping

from sqlmodel import Session

from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import run_tailor_review
from resume_agent.tracking.repository import save_job, save_resume_version
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def tailor_job(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
) -> list[ResumeVersion]:
    """Run the loop for one job, persist each round as a ResumeVersion, mark the job tailored."""
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    rounds = run_tailor_review(
        job.jd_text, criteria, profile_facts, config, tailor_agent, reviewer_agents, reviser_agent
    )
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
