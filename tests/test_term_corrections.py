from __future__ import annotations

import json

import pytest

from resume_agent.taxonomy.term_typing import TermSource, type_term


def _decision():
    return type_term(
        TermSource.without_offsets(
            source_kind="profile_skill",
            source_id="skill:leadership",
            original_text="Leadership",
        )
    )


def test_correction_event_replays_as_a_scoped_auditable_decision(tmp_path):
    from resume_agent.taxonomy.term_corrections import (
        TermTypeCorrection,
        apply_term_type_corrections,
        load_term_type_corrections,
        save_term_type_corrections,
    )

    decision = _decision()
    correction = TermTypeCorrection.create(
        actor_id="user:7",
        scope="profile",
        action="set_type",
        subject_decision_id=decision.id,
        prior_type="unknown",
        new_type="capability",
        rationale="Backed by reviewed profile evidence",
        evidence_refs=["exp:1:bullet:2"],
        target_revision=decision.policy_revision,
        timestamp="2026-08-19T12:00:00Z",
    )
    path = tmp_path / "term_type_corrections.json"
    save_term_type_corrections([correction], path)

    loaded = load_term_type_corrections(path)
    corrected = apply_term_type_corrections([decision], loaded)

    assert loaded == [correction]
    assert corrected[0].concept_type == "capability"
    assert corrected[0].decision_source == "correction"
    assert corrected[0].reason_code == f"correction:{correction.id}"
    assert correction.actor_id == "user:7"
    assert correction.evidence_refs == ["exp:1:bullet:2"]


def test_correction_replay_is_deterministic_and_last_event_wins():
    from resume_agent.taxonomy.term_corrections import (
        TermTypeCorrection,
        apply_term_type_corrections,
    )

    decision = _decision()
    first = TermTypeCorrection.create(
        actor_id="user:7",
        scope="profile",
        action="set_type",
        subject_decision_id=decision.id,
        prior_type="unknown",
        new_type="skill",
        rationale="Initial review",
        evidence_refs=[],
        target_revision=decision.policy_revision,
        timestamp="2026-08-19T12:00:00Z",
    )
    second = TermTypeCorrection.create(
        actor_id="user:7",
        scope="profile",
        action="set_type",
        subject_decision_id=decision.id,
        prior_type="skill",
        new_type="capability",
        rationale="Second review",
        evidence_refs=[],
        target_revision=decision.policy_revision,
        timestamp="2026-08-19T13:00:00Z",
    )

    forward = apply_term_type_corrections([decision], [first, second])
    reversed_input = apply_term_type_corrections([decision], [second, first])

    assert forward == reversed_input
    assert forward[0].concept_type == "capability"


def test_stale_or_mismatched_corrections_are_rejected():
    from resume_agent.taxonomy.term_corrections import (
        TermTypeCorrection,
        apply_term_type_corrections,
    )

    decision = _decision()
    stale = TermTypeCorrection.create(
        actor_id="user:7",
        scope="profile",
        action="set_type",
        subject_decision_id=decision.id,
        prior_type="unknown",
        new_type="capability",
        rationale="Old policy",
        evidence_refs=[],
        target_revision="term-typing-v0",
        timestamp="2026-08-19T12:00:00Z",
    )

    with pytest.raises(ValueError, match="targets policy revision"):
        apply_term_type_corrections([decision], [stale])


def test_correction_store_is_atomic_json_and_missing_file_is_empty(tmp_path):
    from resume_agent.taxonomy.term_corrections import (
        load_term_type_corrections,
        save_term_type_corrections,
    )

    path = tmp_path / "nested" / "term_type_corrections.json"
    assert load_term_type_corrections(path) == []

    save_term_type_corrections([], path)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "events": [],
    }
    assert list(path.parent.glob("*.tmp")) == []

