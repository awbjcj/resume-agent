"""Career Lab's durable transcript and role invariants."""

import pytest
from pydantic import ValidationError

from resume_agent.career_lab.models import (
    CareerLabArtifactMeta,
    CareerLabSession,
    CareerLabTurnRecord,
)
from resume_agent.career_lab.store import (
    active_session_for_job,
    append_clarification_turns,
    append_turns,
    create_session,
    delete_sessions_for_job,
    list_sessions,
    load_session,
    rename_session,
)


def test_assistant_turn_requires_agent_metadata():
    with pytest.raises(ValidationError):
        CareerLabTurnRecord(
            turn_id="t1",
            role="assistant",
            text="draft",
            at="2026-08-02T00:00:00+00:00",
        )


def test_assistant_turn_accepts_tool_free_router_clarification():
    from resume_agent.career_skills.models import AgentFamily, AgentRunMeta

    turn = CareerLabTurnRecord(
        turn_id="t1",
        role="assistant",
        text="What outcome do you want?",
        at="2026-08-02T00:00:00+00:00",
        agent_meta=AgentRunMeta(
            agent_family=AgentFamily.CAREER_LAB,
            prompt_policy_version="career-lab-router-v2",
            model_id="test",
        ),
    )

    assert turn.skill_ref is None
    assert turn.agent_meta is not None


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


def test_session_store_enforces_one_active_unanchored_session(tmp_path):
    first = create_session(tmp_path, session_id="first", goal="goal")
    assert first["status"] == "active"
    assert first["job_id"] is None
    with pytest.raises(ValueError, match="active Career Lab session"):
        create_session(tmp_path, session_id="second")


def test_active_sessions_are_scoped_per_job(tmp_path):
    """A thread about one role must not block opening one about another."""
    create_session(tmp_path, session_id="unanchored")
    seven = create_session(tmp_path, session_id="job-seven", job_id=7)
    nine = create_session(tmp_path, session_id="job-nine", job_id=9)
    assert (seven["job_id"], nine["job_id"]) == (7, 9)

    with pytest.raises(ValueError, match="active Career Lab session"):
        create_session(tmp_path, session_id="job-seven-again", job_id=7)


def test_active_session_for_job_selects_by_anchor(tmp_path):
    create_session(tmp_path, session_id="unanchored")
    create_session(tmp_path, session_id="job-seven", job_id=7)

    job_session = active_session_for_job(tmp_path, 7)
    assert job_session is not None
    assert job_session["session_id"] == "job-seven"

    unanchored_session = active_session_for_job(tmp_path, None)
    assert unanchored_session is not None
    assert unanchored_session["session_id"] == "unanchored"
    assert active_session_for_job(tmp_path, 404) is None


def test_list_sessions_filters_by_job(tmp_path):
    create_session(tmp_path, session_id="unanchored")
    create_session(tmp_path, session_id="job-seven", job_id=7)

    assert [row["session_id"] for row in list_sessions(tmp_path, job_id=7)] == [
        "job-seven"
    ]
    # No filter still returns every thread, anchored or not.
    assert len(list_sessions(tmp_path)) == 2


def test_delete_sessions_for_job_spares_other_threads(tmp_path):
    create_session(tmp_path, session_id="unanchored")
    create_session(tmp_path, session_id="job-seven", job_id=7)
    create_session(tmp_path, session_id="job-nine", job_id=9)

    assert delete_sessions_for_job(tmp_path, 7) == 1
    assert sorted(row["session_id"] for row in list_sessions(tmp_path)) == [
        "job-nine",
        "unanchored",
    ]
    assert delete_sessions_for_job(tmp_path, 7) == 0


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


def test_append_clarification_turns_round_trips_without_a_skill(tmp_path):
    create_session(tmp_path, session_id="s1")
    from resume_agent.career_skills.models import AgentFamily, AgentRunMeta

    append_clarification_turns(
        tmp_path,
        "s1",
        user_text="Research this company.",
        context_refs={},
        assistant_text="What outcome should the research support?",
        agent_meta=AgentRunMeta(
            agent_family=AgentFamily.CAREER_LAB,
            prompt_policy_version="career-lab-router-v2",
            model_id="test",
        ),
    )

    session = load_session(tmp_path, "s1")
    assistant = session["turns"][1]
    assert assistant["skill_ref"] is None
    assert assistant["agent_meta"]["skill_ref"] is None


def test_store_model_accepts_legacy_empty_turns():
    session = CareerLabSession(session_id="s1", started_at="2026-08-02T00:00:00+00:00")
    assert session.turns == []


def test_rename_session_changes_title_without_changing_goal(tmp_path):
    create_session(tmp_path, session_id="s1", goal="Prepare negotiation points")

    renamed = rename_session(tmp_path, "s1", "  Equity trade-offs  ")

    assert renamed["title"] == "Equity trade-offs"
    assert renamed["goal"] == "Prepare negotiation points"


def test_rename_session_rejects_an_empty_title(tmp_path):
    create_session(tmp_path, session_id="s1", goal="Prepare negotiation points")

    with pytest.raises(ValueError, match="title is empty"):
        rename_session(tmp_path, "s1", "   ")
