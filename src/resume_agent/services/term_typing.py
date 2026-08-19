"""Application service for tenant-scoped term typing and corrections."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from sqlmodel import Session

from resume_agent.taxonomy.term_corrections import (
    TermTypeCorrection,
    apply_term_type_corrections,
    load_term_type_corrections,
    save_term_type_corrections,
)
from resume_agent.taxonomy.term_typing import (
    TermConceptType,
    TermSource,
    TermTypingDecision,
    type_term,
)
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.job import JobCriteria
from resume_agent.discovery.requirements import bind_job_requirements
from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.profile.matrix import rebuild_saved_matrix
from resume_agent.profile.store import load_facts
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job


class TermDecisionMismatchError(ValueError):
    pass


class JobRequirementNotFoundError(LookupError):
    pass


def classify_term(
    source: TermSource,
    *,
    corrections_path: str | Path,
) -> TermTypingDecision:
    decision = type_term(source)
    return apply_term_type_corrections(
        [decision], load_term_type_corrections(corrections_path)
    )[0]


def correct_term(
    source: TermSource,
    *,
    decision_id: str,
    new_type: TermConceptType,
    rationale: str,
    evidence_refs: list[str],
    actor_id: str,
    corrections_path: str | Path,
    timestamp: str | None = None,
) -> TermTypingDecision:
    current = classify_term(source, corrections_path=corrections_path)
    if current.id != decision_id:
        raise TermDecisionMismatchError(
            "path decision ID does not match the supplied source"
        )
    event = TermTypeCorrection.create(
        actor_id=actor_id,
        scope="profile",
        action="set_type",
        subject_decision_id=current.id,
        prior_type=current.concept_type,
        new_type=new_type,
        rationale=rationale,
        evidence_refs=evidence_refs,
        target_revision=current.policy_revision,
        timestamp=timestamp
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    events = load_term_type_corrections(corrections_path)
    save_term_type_corrections([*events, event], corrections_path)
    return apply_term_type_corrections([current], [event])[0]


def correct_term_and_rebuild_profile(
    source: TermSource,
    *,
    decision_id: str,
    new_type: TermConceptType,
    rationale: str,
    evidence_refs: list[str],
    actor_id: str,
    corrections_path: str | Path,
    profile_dir: str | Path,
    facts_path: str | Path,
    session: Session | None = None,
) -> TermTypingDecision:
    """Persist one correction, then refresh the affected derived projections."""
    decision = correct_term(
        source,
        decision_id=decision_id,
        new_type=new_type,
        rationale=rationale,
        evidence_refs=evidence_refs,
        actor_id=actor_id,
        corrections_path=corrections_path,
    )
    profile_dir = Path(profile_dir)
    taxonomy = build_effective_taxonomy(
        profile_dir,
        term_corrections_path=corrections_path,
    )
    try:
        facts = load_facts(facts_path)
    except OSError:
        facts = None
    if isinstance(facts, ProfileFacts):
        rebuild_saved_matrix(profile_dir, facts, taxonomy=taxonomy)
    job_match = re.fullmatch(r"job:(\d+):(?:must|nice|tech|derived):\d+", source.source_id)
    if session is not None and job_match is not None:
        job_id = int(job_match.group(1))
        job = session.get(Job, job_id)
        if job is not None:
            criteria = JobCriteria.model_validate(job.criteria_json or {})
            rebound = bind_job_requirements(
                criteria,
                job_id=job_id,
                jd_text=job.jd_text,
                taxonomy_revision=taxonomy.semantic_revision,
                aliases=taxonomy.cluster_map.aliases,
                term_corrections=list(taxonomy.term_type_corrections),
            )
            job.criteria_json = rebound.model_dump(mode="json")
            save_job(session, job)
    return decision


def correct_job_requirement(
    session: Session,
    *,
    job_id: int,
    requirement_id: str,
    new_type: TermConceptType,
    rationale: str,
    evidence_refs: list[str],
    actor_id: str,
    corrections_path: str | Path,
    profile_dir: str | Path,
    facts_path: str | Path,
) -> TermTypingDecision:
    job = session.get(Job, job_id)
    if job is None:
        raise JobRequirementNotFoundError("job requirement was not found")
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    requirement = next(
        (item for item in criteria.typed_requirements if item.id == requirement_id),
        None,
    )
    if requirement is None:
        raise JobRequirementNotFoundError("job requirement was not found")
    source_id = (
        f"job:{job_id}:{requirement.legacy_source}:{requirement.legacy_order}"
    )
    if requirement.source_start is not None and requirement.source_end is not None:
        source = TermSource.from_text(
            source_kind="job_description",
            source_id=source_id,
            source_text=job.jd_text,
            original_text=job.jd_text[
                requirement.source_start : requirement.source_end
            ],
            start=requirement.source_start,
        )
    else:
        source = TermSource.without_offsets(
            source_kind="job_criteria",
            source_id=source_id,
            original_text=requirement.source_text,
        )
    return correct_term_and_rebuild_profile(
        source,
        decision_id=requirement.term_decision_id,
        new_type=new_type,
        rationale=rationale,
        evidence_refs=evidence_refs,
        actor_id=actor_id,
        corrections_path=corrections_path,
        profile_dir=profile_dir,
        facts_path=facts_path,
        session=session,
    )
