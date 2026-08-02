"""Prompt-driven cover-letter revision service."""

from __future__ import annotations

from sqlmodel import Session

from resume_agent.career_skills.provenance import append_skill_use
from resume_agent.cover_letter.provenance import collect_fact_ids, unsupported_provenance
from resume_agent.cover_letter.render import render_cover_letter
from resume_agent.cover_letter.revision import apply_revision, compose_user_revision_input
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.profile.store import load_facts
from resume_agent.services.agents import CoverLetterBundle, build_cover_letter_bundle
from resume_agent.tracking.repository import get_cover_letter, save_cover_letter
from resume_agent.tracking.tables import CoverLetter
from resume_agent.tenancy.paths import FACTS_PATH as DEFAULT_FACTS


def revise_cover_letter_version(
    session: Session,
    cover_letter_id: int,
    instruction: str,
    *,
    facts_path: str = DEFAULT_FACTS,
    bundle: CoverLetterBundle | None = None,
) -> CoverLetter | None:
    parent = get_cover_letter(session, cover_letter_id)
    if parent is None:
        return None

    facts = load_facts(facts_path)
    bundle = bundle or build_cover_letter_bundle()
    current = CoverLetterContent.model_validate(parent.content_json or {})
    revised = apply_revision(
        compose_user_revision_input(current, instruction, facts),
        bundle.revision,
    )

    bad = unsupported_provenance(revised, collect_fact_ids(facts))
    skill_uses = parent.skill_uses_json
    if getattr(bundle.revision, "run_meta", None) is not None:
        skill_uses = append_skill_use(skill_uses, bundle.revision, "revised")
    child = save_cover_letter(
        session,
        CoverLetter(
            job_id=parent.job_id,
            resume_version_id=parent.resume_version_id,
            content_json=revised.model_dump(mode="json"),
            fact_check_passed=not bad,
            origin="revision",
            instruction=instruction,
            parent_id=parent.id,
            skill_uses_json=skill_uses,
        ),
    )
    if child.id is None:
        raise RuntimeError("Revised cover letter was not persisted")
    render_cover_letter(session, child.id)
    return child
