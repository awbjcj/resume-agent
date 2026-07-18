"""Interview router: guards, singleton semantics, lifecycle, views."""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import interview as interview_router
from resume_agent.db import get_session
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
    def __init__(self, outputs):
        self._outputs = list(outputs)

    def run(self, prompt):
        return SimpleNamespace(content=self._outputs.pop(0))


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


def _seed(client, *, jd_text="Ship Python services", version_job=None):
    """Insert a Job (+ ResumeVersion) via the app engine. Returns (job_id, version_id)."""
    engine = client.app.state.engine
    with get_session(engine) as db:
        job = Job(source="manual", company="Acme", title="Engineer", jd_text=jd_text)
        db.add(job)
        db.commit()
        db.refresh(job)
        version = ResumeVersion(
            job_id=version_job if version_job is not None else job.id,
            content_json={"summary": "Builder"},
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        return job.id, version.id


def _wait(client, run_id):
    for _ in range(200):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in {"done", "error"}:
            return run
        time.sleep(0.02)
    raise AssertionError("run never finished")


def _fake_agents(monkeypatch):
    monkeypatch.setattr(interview_router, "resolve_api_key", lambda model: "key")
    monkeypatch.setattr(service, "build_interviewer_agent", lambda style: FakeRunner(["notes"]))
    monkeypatch.setattr(service, "build_debrief_agent", lambda: FakeRunner(["debrief notes"]))

    def formatter(schema):
        if schema is OpeningInterview:
            return FakeRunner([
                OpeningInterview(
                    message="Welcome. Tell me about yourself.",
                    plan=[
                        NewPlanItem(competency="Python", question_type="role_specific"),
                        NewPlanItem(competency="Ownership", question_type="behavioral"),
                    ],
                )
            ])
        if schema is InterviewTurn:
            return FakeRunner([
                InterviewTurn(message="That's all from me, thank you.", action="conclude")
            ])
        return FakeRunner([
            DebriefTurn(
                summary="Solid rehearsal.",
                question_reviews=[ReviewItem(question_id="q1", question="Intro", score=4)],
            )
        ])

    monkeypatch.setattr(service, "build_interview_formatter_agent", formatter)


def test_start_requires_known_job(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(interview_router, "resolve_api_key", lambda model: "key")
    with client:
        response = client.post(
            "/api/interview/sessions",
            json={"jobId": 999, "resumeVersionId": 1, "style": {}},
        )
        assert response.status_code == 404


def test_start_rejects_version_from_other_job(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(interview_router, "resolve_api_key", lambda model: "key")
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
    monkeypatch.setattr(interview_router, "resolve_api_key", lambda model: "key")
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
            json={"jobId": job_id, "resumeVersionId": version_id, "style": {"questionCount": 4}},
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
            f"/api/interview/sessions/{session_id}/messages", json={"message": "My answer"}
        )
        assert message.status_code == 202
        _wait(client, message.json()["runId"])

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
