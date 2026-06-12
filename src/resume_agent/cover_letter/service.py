from sqlmodel import Session

from resume_agent.cover_letter.drafting import (
    compose_cover_letter_input,
    compose_revise_input,
    draft_cover_letter,
    revise_cover_letter,
)
from resume_agent.cover_letter.provenance import collect_fact_ids, unsupported_provenance
from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.repository import save_cover_letter
from resume_agent.tracking.tables import CoverLetter, Job


def generate_cover_letter(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    draft_agent: Runner,
    reviser_agent: Runner,
    max_rounds: int = 2,
) -> CoverLetter:
    """Draft a cover letter, revise until provenance is clean or max_rounds is reached."""
    if job.id is None:
        raise ValueError("Cannot write a cover letter for a job that has not been persisted")
    fact_ids = collect_fact_ids(profile_facts)
    criteria = JobCriteria.model_validate(job.criteria_json or {})

    content = draft_cover_letter(
        compose_cover_letter_input(job.jd_text, criteria, profile_facts), draft_agent
    )
    for _ in range(max_rounds - 1):
        bad = unsupported_provenance(content, fact_ids)
        if not bad:
            break
        content = revise_cover_letter(
            compose_revise_input(content, bad, profile_facts, job.jd_text), reviser_agent
        )

    passed = not unsupported_provenance(content, fact_ids)
    cover = CoverLetter(
        job_id=job.id,
        content_json=content.model_dump(mode="json"),
        fact_check_passed=passed,
    )
    return save_cover_letter(session, cover)
