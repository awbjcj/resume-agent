"""Tailor use-case: resolve targets, load config/facts, build agents, run the loop."""

from __future__ import annotations

from sqlmodel import Session

from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.render.export import export_job_artifacts
from resume_agent.services.agents import TailorBundle, build_tailor_bundle  # noqa: F401  (TailorBundle re-exported for callers/tests)
from resume_agent.tailor.review_config import load_review_config
from resume_agent.tailor.service import tailor_jobs
from resume_agent.tailor.style_guide import load_style_guide
from resume_agent.tracking.repository import get_job, jobs_by_status
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion

DEFAULT_REVIEW = "config/review.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


def resolve_targets(session: Session, *, job_ids: list[int] | None, approved: bool) -> list[Job]:
    if job_ids:
        found = [get_job(session, jid) for jid in job_ids]
        return [j for j in found if j is not None]
    if approved:
        return jobs_by_status(session, JobStatus.approved.value)
    return []


def tailor(
    session: Session,
    *,
    job_ids: list[int] | None = None,
    approved: bool = False,
    review_path: str = DEFAULT_REVIEW,
    facts_path: str = DEFAULT_FACTS,
    reporter: ProgressReporter | None = None,
    fail_on_partial: bool = False,
) -> dict[int, list[ResumeVersion]]:
    targets = resolve_targets(session, job_ids=job_ids, approved=approved)
    if not targets:
        return {}
    config = load_review_config(review_path)
    facts = load_facts(facts_path)
    style_guide = load_style_guide(config.style_guide_path)
    bundle = build_tailor_bundle(config, style_guide=style_guide)
    results = tailor_jobs(
        session, targets, facts, config,
        bundle.tailor, bundle.reviewers, bundle.reviser, reporter=reporter,
        match_plan_agent=bundle.match_plan,
    )
    for job_id in results:
        export_job_artifacts(session, job_id)
    if fail_on_partial and len(results) != len(targets):
        failed_ids = [str(job.id) for job in targets if job.id not in results]
        raise RuntimeError(
            f"Tailoring failed for {len(failed_ids)} of {len(targets)} jobs "
            f"(job IDs: {', '.join(failed_ids)})"
        )
    return results
