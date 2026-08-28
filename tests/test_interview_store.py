"""Interview session store: lifecycle, plan transitions, delta-under-lock."""

import pytest

from resume_agent.interview.store import (
    InterviewContext,
    InterviewDebrief,
    InterviewStyle,
    InterviewTurnRecord,
    PlanItem,
    QuestionReview,
    active_session,
    active_session_for_job,
    active_sessions,
    archive_session,
    attach_turn_audio,
    apply_answer_delta,
    create_session,
    delete_session,
    delete_sessions_for_job,
    end_with_debrief,
    list_sessions,
    load_session,
    unarchive_session,
)


def _make(tmp_path, session_id="abc123", job_id=7):
    create_session(
        tmp_path,
        session_id,
        job_id=job_id,
        resume_version_id=3,
        style=InterviewStyle(),
        context=InterviewContext(company="Acme", title="Engineer", jd_text="Build things"),
        plan=[
            PlanItem(id="q1", competency="Leadership", question_type="behavioral"),
            PlanItem(id="q2", competency="Python", question_type="role_specific"),
        ],
        opening_turn=InterviewTurnRecord(
            role="interviewer", text="Tell me about yourself.", question_id="q1"
        ),
    )
    return session_id


def test_create_marks_opening_question_asked(tmp_path):
    sid = _make(tmp_path)
    session = load_session(tmp_path, sid)
    assert session["status"] == "active"
    assert session["job_id"] == 7
    assert session["turns"][0]["role"] == "interviewer"
    assert {p["id"]: p["status"] for p in session["plan"]} == {"q1": "asked", "q2": "pending"}
    assert session["concluded"] is False


def test_second_active_session_rejected(tmp_path):
    _make(tmp_path)
    with pytest.raises(ValueError, match="active session exists"):
        _make(tmp_path, session_id="other99")


def test_active_sessions_are_scoped_per_job(tmp_path):
    _make(tmp_path, session_id="first01", job_id=7)
    _make(tmp_path, session_id="second02", job_id=8)

    assert {row["session_id"] for row in active_sessions(tmp_path)} == {
        "first01",
        "second02",
    }
    first = active_session_for_job(tmp_path, 7)
    assert first is not None
    assert first["session_id"] == "first01"
    assert active_session_for_job(tmp_path, 9) is None


def test_answer_delta_advances_plan(tmp_path):
    sid = _make(tmp_path)
    apply_answer_delta(
        tmp_path,
        sid,
        answer_text="I led a team of five.",
        interviewer_turn=InterviewTurnRecord(
            role="interviewer", text="What Python have you shipped?", question_id="q2"
        ),
        concluded=False,
    )
    session = load_session(tmp_path, sid)
    assert [t["role"] for t in session["turns"]] == ["interviewer", "candidate", "interviewer"]
    assert {p["id"]: p["status"] for p in session["plan"]} == {"q1": "done", "q2": "asked"}


def test_followup_keeps_plan_statuses(tmp_path):
    sid = _make(tmp_path)
    apply_answer_delta(
        tmp_path,
        sid,
        answer_text="We improved things.",
        interviewer_turn=InterviewTurnRecord(
            role="interviewer", text="How did you measure that?", question_id="q1", is_followup=True
        ),
        concluded=False,
    )
    session = load_session(tmp_path, sid)
    assert {p["id"]: p["status"] for p in session["plan"]} == {"q1": "asked", "q2": "pending"}


def test_conclude_marks_asked_done(tmp_path):
    sid = _make(tmp_path)
    apply_answer_delta(
        tmp_path,
        sid,
        answer_text="Thanks!",
        interviewer_turn=InterviewTurnRecord(role="interviewer", text="That's all from me."),
        concluded=True,
    )
    session = load_session(tmp_path, sid)
    assert session["concluded"] is True
    assert {p["id"]: p["status"] for p in session["plan"]} == {"q1": "done", "q2": "pending"}


def test_end_with_debrief_and_double_end_rejected(tmp_path):
    sid = _make(tmp_path)
    debrief = InterviewDebrief(
        summary="Solid rehearsal.",
        question_reviews=[
            QuestionReview(question_id="q1", question="Tell me about yourself.", score=4)
        ],
    )
    end_with_debrief(tmp_path, sid, debrief)
    session = load_session(tmp_path, sid)
    assert session["status"] == "ended"
    assert session["debrief"]["summary"] == "Solid rehearsal."
    assert active_session(tmp_path) is None
    with pytest.raises(ValueError, match="session ended"):
        end_with_debrief(tmp_path, sid, debrief)


def test_delta_on_ended_session_rejected(tmp_path):
    sid = _make(tmp_path)
    end_with_debrief(tmp_path, sid, InterviewDebrief(summary="x"))
    with pytest.raises(ValueError, match="session ended"):
        apply_answer_delta(
            tmp_path,
            sid,
            answer_text="hello",
            interviewer_turn=InterviewTurnRecord(role="interviewer", text="Q", question_id="q1"),
            concluded=False,
        )


def test_list_sessions_filters_by_job_and_delete(tmp_path):
    sid = _make(tmp_path, job_id=7)
    end_with_debrief(tmp_path, sid, InterviewDebrief(summary="x"))
    _make(tmp_path, session_id="zzz111", job_id=8)
    assert [s["job_id"] for s in list_sessions(tmp_path, job_id=7)] == [7]
    assert len(list_sessions(tmp_path)) == 2
    assert delete_sessions_for_job(tmp_path, 7) == 1
    assert list_sessions(tmp_path, job_id=7) == []


def test_archive_unarchive_and_delete_session(tmp_path):
    sid = _make(tmp_path)
    with pytest.raises(ValueError, match="only ended sessions"):
        archive_session(tmp_path, sid)

    end_with_debrief(tmp_path, sid, InterviewDebrief(summary="done"))
    archived = archive_session(tmp_path, sid)
    assert archived["archived_at"]
    assert list_sessions(tmp_path) == []
    assert [
        row["session_id"]
        for row in list_sessions(tmp_path, include_archived=True)
    ] == [sid]

    assert unarchive_session(tmp_path, sid)["archived_at"] is None
    with pytest.raises(ValueError, match="not archived"):
        unarchive_session(tmp_path, sid)

    audio_path = attach_turn_audio(tmp_path, sid, 0, b"mp3")
    assert audio_path.read_bytes() == b"mp3"

    delete_session(tmp_path, sid)
    assert list_sessions(tmp_path, include_archived=True) == []
    assert not audio_path.exists()
    with pytest.raises(ValueError, match="unknown session"):
        delete_session(tmp_path, sid)


def test_delete_sessions_for_job_includes_archived(tmp_path):
    sid = _make(tmp_path)
    end_with_debrief(tmp_path, sid, InterviewDebrief(summary="done"))
    archive_session(tmp_path, sid)

    assert delete_sessions_for_job(tmp_path, 7) == 1


def test_unknown_session_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown session"):
        load_session(tmp_path, "missing0")
