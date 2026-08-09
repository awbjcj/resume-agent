"""Prompt-driven resume revision service."""

from __future__ import annotations

from sqlmodel import Session

from resume_agent.models.resume import ResumeContent
from resume_agent.models.evidence_portfolio import EvidencePortfolio
from resume_agent.career_skills.provenance import append_skill_use
from resume_agent.profile.store import load_facts
from resume_agent.render.export import export_job_artifacts
from resume_agent.services.agents import TailorBundle, build_tailor_bundle
from resume_agent.tailor.panel import run_panel
from resume_agent.tailor.provenance import provenance_critique
from resume_agent.tailor.review_config import load_review_config
from resume_agent.tailor.revision import apply_revision, compose_user_revision_input
from resume_agent.tailor.style_guide import load_style_guide
from resume_agent.tailor.verdict import aggregate
from resume_agent.tracking.repository import (
    get_job,
    get_resume_version,
    save_resume_version,
)
from resume_agent.tracking.tables import ResumeVersion

from resume_agent.tenancy.paths import (
    FACTS_PATH as DEFAULT_FACTS,
    REVIEW_PATH as DEFAULT_REVIEW,
)


def revise_resume_version(
    session: Session,
    version_id: int,
    instruction: str,
    *,
    re_review: bool = False,
    review_path: str = DEFAULT_REVIEW,
    facts_path: str = DEFAULT_FACTS,
    bundle: TailorBundle | None = None,
) -> ResumeVersion | None:
    parent = get_resume_version(session, version_id)
    if parent is None:
        return None

    facts = load_facts(facts_path)
    config = load_review_config(review_path) if re_review or bundle is None else None
    if bundle is None:
        assert config is not None
        style_guide = load_style_guide(config.style_guide_path)
        bundle = build_tailor_bundle(config, style_guide=style_guide)

    current = ResumeContent.model_validate(parent.content_json or {})
    revised = apply_revision(
        compose_user_revision_input(current, instruction, facts),
        bundle.revision,
    )

    provenance = provenance_critique(revised, facts)
    critiques = [provenance]
    review_score = None
    fact_check_passed = provenance.passed
    # No panel ran unless re-reviewed, so no reviewer-configured gate applies
    # to this round yet - an empty (known) roster, not None/"unknown".
    gate_reviewers: list[str] = []
    job = get_job(session, parent.job_id)

    if re_review and provenance.passed and job is not None:
        assert config is not None
        critiques.extend(
            run_panel(revised, facts, job.jd_text, config, bundle.reviewers)
        )
        verdict = aggregate(critiques, config)
        review_score = verdict.aggregate_score
        fact_check_passed = verdict.gate_passed
        gate_reviewers = sorted(r.name for r in config.reviewers if r.gate)

    skill_uses = parent.skill_uses_json
    if getattr(bundle.revision, "run_meta", None) is not None:
        skill_uses = append_skill_use(skill_uses, bundle.revision, "revised")
    inherited_portfolio = None
    if parent.evidence_portfolio_json is not None:
        inherited_portfolio = EvidencePortfolio.model_validate(
            parent.evidence_portfolio_json
        ).model_copy(update={"status": "inherited"})
    child = save_resume_version(
        session,
        ResumeVersion(
            job_id=parent.job_id,
            round=parent.round,
            content_json=revised.model_dump(mode="json"),
            review_score=review_score,
            fact_check_passed=fact_check_passed,
            critique_json=[c.model_dump(mode="json") for c in critiques],
            evidence_portfolio_json=(
                inherited_portfolio.model_dump(mode="json")
                if inherited_portfolio is not None
                else None
            ),
            evidence_portfolio_status=(
                inherited_portfolio.status if inherited_portfolio is not None else None
            ),
            gate_reviewers_json=gate_reviewers,
            origin="revision",
            instruction=instruction,
            parent_version_id=parent.id,
            skill_uses_json=skill_uses,
        ),
    )
    export_job_artifacts(session, child.job_id)
    return child
