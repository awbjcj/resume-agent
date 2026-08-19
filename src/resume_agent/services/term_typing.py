"""Application service for tenant-scoped term typing and corrections."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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


class TermDecisionMismatchError(ValueError):
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
