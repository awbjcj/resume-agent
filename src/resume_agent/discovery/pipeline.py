from sqlmodel import Session

from resume_agent.discovery.extract import Runner, extract_job_criteria
from resume_agent.discovery.filter import apply_filters
from resume_agent.discovery.fit import compose_fit_input, score_fit
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.repository import jobs_by_status, status_counts
from resume_agent.tracking.tables import JobStatus


_REEXTRACT_STATUSES = (
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
    JobStatus.shortlisted.value,
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
)


def run_extract(session: Session, agent: Runner) -> None:
    for job in jobs_by_status(session, JobStatus.raw.value):
        criteria = extract_job_criteria(job.jd_text, agent)
        job.criteria_json = criteria.model_dump(mode="json")
        job.status = JobStatus.extracted.value
        session.add(job)
    session.commit()


def run_filter(session: Session, config: SearchConfig) -> None:
    for job in jobs_by_status(session, JobStatus.extracted.value):
        criteria = JobCriteria.model_validate(job.criteria_json or {})
        decision = apply_filters(criteria, config)
        if decision.keep:
            job.status = JobStatus.filtered.value
        else:
            job.status = JobStatus.rejected.value
            job.reject_reason = decision.reject_reason
        session.add(job)
    session.commit()


def run_score(session: Session, profile_facts: ProfileFacts, agent: Runner) -> None:
    for job in jobs_by_status(session, JobStatus.filtered.value):
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts), agent)
        job.fit_score = fit.score
        job.fit_rationale = fit.rationale
        job.status = JobStatus.shortlisted.value
        session.add(job)
    session.commit()


def reextract(session: Session, agent: Runner) -> int:
    """Re-run extraction over already-processed jobs, rewriting criteria_json in place.

    Does not change status or fit. Returns the number of jobs updated.
    """
    updated = 0
    for status in _REEXTRACT_STATUSES:
        for job in jobs_by_status(session, status):
            if not job.jd_text.strip():
                continue
            criteria = extract_job_criteria(job.jd_text, agent)
            job.criteria_json = criteria.model_dump(mode="json")
            session.add(job)
            updated += 1
    session.commit()
    return updated


def discover(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
) -> dict[str, int]:
    """Run the full funnel over current rows and return final status counts."""
    run_extract(session, extract_agent)
    run_filter(session, config)
    run_score(session, profile_facts, fit_agent)
    return status_counts(session)
