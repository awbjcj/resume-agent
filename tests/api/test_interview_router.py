"""Interview router: guards, singleton semantics, lifecycle, views."""

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.interview.store import (
    InterviewContext,
    InterviewDebrief,
    InterviewStyle,
    InterviewTurnRecord,
    PlanItem,
    attach_turn_audio,
    create_session,
    end_with_debrief,
)
from resume_agent.interview.agent import (
    DebriefTurn,
    InterviewTurn,
    NewPlanItem,
    OpeningInterview,
    ReviewItem,
)
from resume_agent.services import mock_interview as service
from resume_agent.tracking.tables import Job, ResumeVersion


class FakeRunner:
    def __init__(self, outputs: list[Any]) -> None:
        self._outputs = list(outputs)

    def run(self, prompt: str) -> Any:
        return SimpleNamespace(content=self._outputs.pop(0))

    async def arun(self, prompt: str) -> Any:
        return self.run(prompt)


def _client(tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    return TestClient(
        create_app(
            db_url="sqlite://",
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            env_path=env,
            api_token="",
        )
    )


def _seed(
    client: TestClient,
    *,
    jd_text: str = "Ship Python services",
    version_job: int | None = None,
) -> tuple[int, int]:
    """Insert a Job (+ ResumeVersion) via the app engine. Returns (job_id, version_id)."""
    engine = cast(FastAPI, client.app).state.engine
    with get_session(engine) as db:
        job = Job(source="manual", company="Acme", title="Engineer", jd_text=jd_text)
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.id is not None
        version = ResumeVersion(
            job_id=version_job if version_job is not None else job.id,
            content_json={"summary": "Builder"},
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        assert version.id is not None
        return job.id, version.id


def _wait(client, run_id):
    for _ in range(200):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in {"done", "error"}:
            return run
        time.sleep(0.02)
    raise AssertionError("run never finished")


def _fake_agents(monkeypatch):
    monkeypatch.setattr(
        "resume_agent.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    monkeypatch.setattr(
        service, "build_interviewer_agent", lambda style: FakeRunner(["notes"])
    )
    monkeypatch.setattr(
        service, "build_debrief_agent", lambda: FakeRunner(["debrief notes"])
    )

    def formatter(schema):
        if schema is OpeningInterview:
            return FakeRunner(
                [
                    OpeningInterview(
                        message="Welcome. Tell me about yourself.",
                        hints=["Use a concrete example.", "Connect it to the role."],
                        plan=[
                            NewPlanItem(
                                competency="Python", question_type="role_specific"
                            ),
                            NewPlanItem(
                                competency="Ownership", question_type="behavioral"
                            ),
                        ],
                    )
                ]
            )
        if schema is InterviewTurn:
            return FakeRunner(
                [
                    InterviewTurn(
                        message="That's all from me, thank you.", action="conclude"
                    )
                ]
            )
        return FakeRunner(
            [
                DebriefTurn(
                    summary="Solid rehearsal.",
                    question_reviews=[
                        ReviewItem(question_id="q1", question="Intro", score=4)
                    ],
                )
            ]
        )

    monkeypatch.setattr(service, "build_interview_formatter_agent", formatter)


def test_start_requires_known_job(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(
        "resume_agent.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    with client:
        response = client.post(
            "/api/interview/sessions",
            json={"jobId": 999, "resumeVersionId": 1, "style": {}},
        )
        assert response.status_code == 404


def test_start_rejects_version_from_other_job(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(
        "resume_agent.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    with client:
        job_id, _ = _seed(client)
        other_job_id, other_version_id = _seed(client)
        response = client.post(
            "/api/interview/sessions",
            json={"jobId": job_id, "resumeVersionId": other_version_id, "style": {}},
        )
        assert response.status_code == 422


def test_start_rejects_job_without_jd(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(
        "resume_agent.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    with client:
        job_id, version_id = _seed(client, jd_text="")
        response = client.post(
            "/api/interview/sessions",
            json={"jobId": job_id, "resumeVersionId": version_id, "style": {}},
        )
        assert response.status_code == 422


def test_full_lifecycle_and_singleton(monkeypatch, tmp_path):
    client = _client(tmp_path)
    _fake_agents(monkeypatch)
    with client:
        job_id, version_id = _seed(client)
        start = client.post(
            "/api/interview/sessions",
            json={
                "jobId": job_id,
                "resumeVersionId": version_id,
                "style": {"questionCount": 4},
            },
        )
        assert start.status_code == 202
        session_id = _wait(client, start.json()["runId"])["result"]["sessionId"]

        conflict = client.post(
            "/api/interview/sessions",
            json={"jobId": job_id, "resumeVersionId": version_id, "style": {}},
        )
        assert conflict.status_code == 409

        detail = client.get(f"/api/interview/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["plan"] is None  # hidden while active

        message = client.post(
            f"/api/interview/sessions/{session_id}/messages",
            json={"message": "My answer"},
        )
        assert message.status_code == 202
        _wait(client, message.json()["runId"])

        # the faked interviewer concluded; further answers are rejected up front
        concluded = client.post(
            f"/api/interview/sessions/{session_id}/messages", json={"message": "more"}
        )
        assert concluded.status_code == 409

        end = client.post(f"/api/interview/sessions/{session_id}/end", json={})
        assert end.status_code == 202
        _wait(client, end.json()["runId"])

        ended = client.get(f"/api/interview/sessions/{session_id}").json()
        assert ended["status"] == "ended"
        assert ended["plan"] is not None
        assert ended["debrief"]["summary"]

        after = client.post(
            f"/api/interview/sessions/{session_id}/messages", json={"message": "hello"}
        )
        assert after.status_code == 409

        listing = client.get(f"/api/interview/sessions?jobId={job_id}").json()
        assert listing["sessions"][0]["sessionId"] == session_id


def test_end_without_an_answer_closes_cleanly(monkeypatch, tmp_path):
    client = _client(tmp_path)
    _fake_agents(monkeypatch)
    with client:
        job_id, version_id = _seed(client)
        start = client.post(
            "/api/interview/sessions",
            json={
                "jobId": job_id,
                "resumeVersionId": version_id,
                "style": {"questionCount": 4},
            },
        )
        assert start.status_code == 202
        session_id = _wait(client, start.json()["runId"])["result"]["sessionId"]

        end = client.post(f"/api/interview/sessions/{session_id}/end", json={})
        assert end.status_code == 202
        completed = _wait(client, end.json()["runId"])

        assert completed["state"] == "done"
        assert completed["result"]["status"] == "ended"
        assert completed["result"]["debrief"]["questionReviews"] == []


def _write_ended_session(
    interview_dir: Path, job_id: int, session_id: str = "ended01"
) -> str:
    create_session(
        interview_dir,
        session_id,
        job_id=job_id,
        resume_version_id=0,
        style=InterviewStyle(),
        context=InterviewContext(company="Acme", title="Engineer", jd_text="Build"),
        plan=[PlanItem(id="q1", competency="Python", question_type="role_specific")],
        opening_turn=InterviewTurnRecord(
            role="interviewer", text="Hi", question_id="q1"
        ),
    )
    end_with_debrief(interview_dir, session_id, InterviewDebrief(summary="done"))
    return session_id


def _write_active_session(
    interview_dir: Path, job_id: int, session_id: str = "active01"
) -> str:
    create_session(
        interview_dir,
        session_id,
        job_id=job_id,
        resume_version_id=0,
        style=InterviewStyle(),
        context=InterviewContext(company="Acme", title="Engineer", jd_text="Build"),
        plan=[PlanItem(id="q1", competency="Python", question_type="role_specific")],
        opening_turn=InterviewTurnRecord(
            role="interviewer", text="Hi", question_id="q1"
        ),
    )
    return session_id


def test_start_conflicts_only_for_the_same_job(monkeypatch, tmp_path):
    client = _client(tmp_path)
    _fake_agents(monkeypatch)
    with client:
        first_job, _ = _seed(client)
        second_job, second_version = _seed(client)
        interview_dir = tmp_path / "data" / "interview"
        _write_active_session(interview_dir, first_job, "blocking01")

        conflict = client.post(
            "/api/interview/sessions",
            json={"jobId": first_job, "resumeVersionId": 0, "style": {}},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"] == {
            "code": "SESSION_ACTIVE_FOR_JOB",
            "message": "An active interview session already exists for this job",
            "details": {"sessionId": "blocking01"},
        }

        started = client.post(
            "/api/interview/sessions",
            json={
                "jobId": second_job,
                "resumeVersionId": second_version,
                "style": {"questionCount": 4},
            },
        )
        assert started.status_code == 202
        assert _wait(client, started.json()["runId"])["state"] == "done"


def test_interview_archive_filters_unarchive_and_delete(tmp_path):
    client = _client(tmp_path)
    with client:
        interview_dir = tmp_path / "data" / "interview"
        session_id = _write_ended_session(interview_dir, 1)

        renamed = client.patch(
            f"/api/interview/sessions/{session_id}",
            json={"title": "Platform interview"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["sessionTitle"] == "Platform interview"

        archived = client.post(f"/api/interview/sessions/{session_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["archivedAt"]
        assert client.get("/api/interview/sessions").json()["sessions"] == []
        included = client.get(
            "/api/interview/sessions", params={"includeArchived": "true"}
        ).json()["sessions"]
        assert [row["sessionId"] for row in included] == [session_id]
        assert included[0]["sessionTitle"] == "Platform interview"

        assert (
            client.post(f"/api/interview/sessions/{session_id}/unarchive").status_code
            == 200
        )
        assert (
            client.post(f"/api/interview/sessions/{session_id}/unarchive").status_code
            == 409
        )
        assert client.delete(f"/api/interview/sessions/{session_id}").status_code == 204
        assert client.delete(f"/api/interview/sessions/{session_id}").status_code == 404


def test_interview_audio_availability_and_protected_turn_delivery(
    monkeypatch, tmp_path
):
    client = _client(tmp_path)
    monkeypatch.setattr("resume_agent.llm_runner.speech_available", lambda: True)
    with client:
        assert client.get("/api/interview/audio/availability").json() == {
            "available": True
        }
        interview_dir = tmp_path / "data" / "interview"
        session_id = _write_active_session(interview_dir, 1, "audio01")
        attach_turn_audio(interview_dir, session_id, 0, b"fake-mp3")

        response = client.get(f"/api/interview/sessions/{session_id}/turns/0/audio")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")
        assert response.content == b"fake-mp3"
        assert (
            client.get(
                f"/api/interview/sessions/{session_id}/turns/9/audio"
            ).status_code
            == 404
        )


def test_interview_archive_rejects_active_and_invalid_status_filter(tmp_path):
    client = _client(tmp_path)
    with client:
        interview_dir = tmp_path / "data" / "interview"
        session_id = _write_active_session(interview_dir, 1)

        assert (
            client.post(f"/api/interview/sessions/{session_id}/archive").status_code
            == 409
        )
        assert (
            client.get(
                "/api/interview/sessions", params={"status": "paused"}
            ).status_code
            == 422
        )


def test_job_delete_removes_interview_sessions(tmp_path):
    client = _client(tmp_path)
    with client:
        engine = cast(FastAPI, client.app).state.engine
        with get_session(engine) as db:
            job = Job(
                source="manual", company="Acme", title="Engineer", jd_text="Build"
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            assert job.id is not None
            job_id = job.id
        interview_dir = tmp_path / "data" / "interview"
        session_id = _write_ended_session(interview_dir, job_id)

        assert client.delete(f"/api/jobs/{job_id}").status_code == 204
        assert client.get(f"/api/interview/sessions/{session_id}").status_code == 404
