"""Status counts + action queues over a seeded DB; archived rows excluded."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.interview.store import (
    InterviewContext,
    InterviewDebrief,
    InterviewStyle,
    InterviewTurnRecord,
    PlanItem,
    QuestionReview,
    create_session,
    end_with_debrief,
)
from resume_tailor_harness.services.errors import record_error
from resume_tailor_harness.tracking.tables import Application, Job


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as c:
        yield c


def _seed(engine):
    with Session(engine) as session:

        def job(status, archived=False, **kw):
            j = Job(
                source="manual",
                company="Acme",
                title=f"{status}-role",
                status=status,
                dedup_key=f"acme|{status}{archived}",
                **kw,
            )
            if archived:
                j.archived_at = datetime.now(timezone.utc)
            session.add(j)
            return j

        job("filtered")
        job("filtered", archived=True)  # must not count
        job("shortlisted")
        job("approved")
        rendered = job("rendered")
        session.commit()
        assert rendered.id is not None
        session.add(Application(job_id=rendered.id, status="submitted"))
        session.commit()


def test_summary_counts_and_queues(client):
    _seed(client.app.state.engine)
    body = client.get("/api/dashboard/summary").json()
    assert body["statusCounts"]["filtered"] == 1  # archived excluded
    assert body["queues"] == {"triage": 1, "approve": 1, "tailor": 1, "apply": 1}
    assert body["applied"] == 1


def test_applied_excludes_archived_jobs(client):
    with Session(client.app.state.engine) as session:
        archived_rendered = Job(
            source="manual",
            company="Acme",
            title="rendered-archived-role",
            status="rendered",
            dedup_key="acme|rendered-archived",
            archived_at=datetime.now(timezone.utc),
        )
        session.add(archived_rendered)
        session.commit()
        assert archived_rendered.id is not None
        session.add(Application(job_id=archived_rendered.id, status="submitted"))
        session.commit()

    body = client.get("/api/dashboard/summary").json()
    assert body["applied"] == 0  # the only Application belongs to an archived job


def test_summary_includes_active_sessions_and_open_error_count(client):
    with Session(client.app.state.engine) as session:
        record_error(session, kind="run", source_label="pull", message="failed")
    create_session(
        client.app.state.data_dir / "interview",
        "active01",
        job_id=1,
        resume_version_id=1,
        style=InterviewStyle(),
        context=InterviewContext(company="Acme", title="Engineer"),
        plan=[PlanItem(id="q1", competency="Python", question_type="technical")],
        opening_turn=InterviewTurnRecord(
            role="interviewer", text="Question", question_id="q1"
        ),
    )

    body = client.get("/api/dashboard/summary").json()

    assert body["openErrorCount"] == 1
    assert body["activeInterviews"][0]["sessionId"] == "active01"
    assert body["activeCoachSession"] is None


def test_summary_includes_practice_progress_and_source_health(client):
    interview_dir = client.app.state.data_dir / "interview"
    for index, scores in enumerate(([2, 3], [4, 5]), start=1):
        session_id = f"ended0{index}"
        create_session(
            interview_dir,
            session_id,
            job_id=index,
            resume_version_id=index,
            style=InterviewStyle(question_count=4),
            context=InterviewContext(company="Acme", title="Engineer"),
            plan=[PlanItem(id="q1", competency="Python", question_type="technical")],
            opening_turn=InterviewTurnRecord(
                role="interviewer", text="Question", question_id="q1"
            ),
        )
        end_with_debrief(
            interview_dir,
            session_id,
            InterviewDebrief(
                summary="Done",
                question_reviews=[
                    QuestionReview(question_id=f"q{score}", score=score)
                    for score in scores
                ],
            ),
        )

    with Session(client.app.state.engine) as session:
        record_error(session, kind="source", source_label="LinkedIn", message="blocked")
        record_error(session, kind="source", source_label="Indeed", message="timeout")

    body = client.get("/api/dashboard/summary").json()

    assert body["practiceStats"] == {
        "completedSessions": 2,
        "scoredSessions": 2,
        "averageScore": 3.5,
        "latestScore": 4.5,
        "changeFromFirst": 2.0,
    }
    assert body["sourceHealth"]["openFailures"] == 2
    assert set(body["sourceHealth"]["affectedSources"]) == {"LinkedIn", "Indeed"}
    assert body["sourceHealth"]["latestFailureAt"] is not None
