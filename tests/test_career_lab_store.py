"""Career Lab's durable transcript and role invariants."""

import pytest
from pydantic import ValidationError

from resume_agent.career_lab.models import (
    CareerLabArtifactMeta,
    CareerLabSession,
    CareerLabTurnRecord,
)
from resume_agent.career_lab.store import (
    append_turns,
    create_session,
    load_session,
)


def test_assistant_turn_requires_exactly_one_skill_ref():
    with pytest.raises(ValidationError):
        CareerLabTurnRecord(
            turn_id="t1",
            role="assistant",
            text="draft",
            at="2026-08-02T00:00:00+00:00",
        )


def test_assistant_turn_requires_matching_run_metadata():
    from resume_agent.career_skills.models import AgentFamily, AgentRunMeta, SkillRef

    skill = SkillRef(
        name="salary-negotiation-prep",
        version="2026-08-02",
        sha256="a" * 64,
        family=AgentFamily.CAREER_LAB,
    )
    with pytest.raises(ValidationError):
        CareerLabTurnRecord(
            turn_id="t1",
            role="assistant",
            text="draft",
            at="2026-08-02T00:00:00+00:00",
            skill_ref=skill,
            agent_meta=AgentRunMeta(
                agent_family=AgentFamily.CAREER_LAB,
                prompt_policy_version="career-lab-v1",
                model_id="test",
            ),
        )


def test_session_store_enforces_one_active_session(tmp_path):
    first = create_session(tmp_path, session_id="first", goal="goal")
    assert first["status"] == "active"
    with pytest.raises(ValueError, match="active Career Lab session"):
        create_session(tmp_path, session_id="second")


def test_append_turns_round_trips_typed_artifact(tmp_path):
    create_session(tmp_path, session_id="s1")
    from resume_agent.career_skills.models import AgentFamily, AgentRunMeta, SkillRef

    skill = SkillRef(
        name="salary-negotiation-prep",
        version="2026-08-02",
        sha256="b" * 64,
        family=AgentFamily.CAREER_LAB,
    )
    meta = AgentRunMeta(
        agent_family=AgentFamily.CAREER_LAB,
        prompt_policy_version="career-lab-v1",
        model_id="test",
        skill_ref=skill,
    )
    append_turns(
        tmp_path,
        "s1",
        user_text="compare these offers",
        context_refs={"offer_application_ids": [7]},
        assistant_text="Here is a draft comparison.",
        skill_ref=skill,
        agent_meta=meta,
        artifact=CareerLabArtifactMeta(
            artifact_type="offer_comparison",
            title="Offer comparison",
            summary="Compare compensation and risk.",
        ),
    )
    session = load_session(tmp_path, "s1")
    assert [turn["role"] for turn in session["turns"]] == ["user", "assistant"]
    assert session["turns"][1]["artifact"]["artifact_type"] == "offer_comparison"


def test_store_model_accepts_legacy_empty_turns():
    session = CareerLabSession(session_id="s1", started_at="2026-08-02T00:00:00+00:00")
    assert session.turns == []
