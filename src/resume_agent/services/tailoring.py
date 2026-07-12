"""Tailor use-case: resolve targets, load config/facts, build agents, run the loop."""

from __future__ import annotations


from sqlmodel import Session

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.matrix import (
    effective_cluster_map,
    load_matrix,
    load_overrides,
)
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.render.export import export_job_artifacts
from resume_agent.services.agents import TailorBundle, build_tailor_bundle  # noqa: F401  (TailorBundle re-exported for callers/tests)
from resume_agent.tailor.review_config import load_review_config
from resume_agent.tailor.service import tailor_jobs
from resume_agent.tailor.style_guide import load_style_guide
from resume_agent.tracking.repository import get_job, jobs_by_status
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion
from resume_agent.taxonomy.clusters import load_cluster_map
from resume_agent.tenancy.limits import enforce_active_budget
from resume_agent.tenancy.paths import resolve_tenant_path

DEFAULT_REVIEW = "config/review.yaml"
DEFAULT_REVIEW_DEEP = "config/review_deep.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


def resolve_targets(
    session: Session, *, job_ids: list[int] | None, approved: bool
) -> list[Job]:
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
    enforce_active_budget()
    facts = load_facts(facts_path)
    profile_dir = resolve_tenant_path(facts_path).parent
    overrides = load_overrides(profile_dir / "overrides.yaml")
    cluster_map = effective_cluster_map(
        load_cluster_map(profile_dir / "cluster_map.json"), overrides
    )
    matrix_facts = facts if isinstance(facts, ProfileFacts) else None
    skill_matrix = load_matrix(
        profile_dir / "matrix.json", facts=matrix_facts, cluster_map=cluster_map
    )
    style_guide = load_style_guide(config.style_guide_path)
    bundle = build_tailor_bundle(config, style_guide=style_guide)
    results = tailor_jobs(
        session,
        targets,
        facts,
        config,
        bundle.tailor,
        bundle.reviewers,
        bundle.reviser,
        reporter=reporter,
        match_plan_agent=bundle.match_plan,
        skill_matrix=skill_matrix,
        cluster_map=cluster_map,
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
