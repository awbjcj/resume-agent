import io
import time
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import profile as profile_router


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


def _seed_primary(client):
    response = client.post(
        "/api/profile/sources",
        files={"file": ("resume.txt", io.BytesIO(b"Acme experience"), "text/plain")},
        data={"primary": "true", "mode": "literal"},
    )
    assert response.status_code == 201


def _fake_round():
    return {
        "roundId": "round-1",
        "questions": [
            {
                "id": "q1",
                "gap": "Acme impact",
                "whyItMatters": "Market demand",
                "questionText": "What measurable impact did you have?",
                "relatedRef": "experience:acme",
            }
        ],
        "researchActions": [],
    }


def _launch_and_wait(client, monkeypatch):
    monkeypatch.setattr(
        profile_router,
        "run_interview_round",
        lambda reporter, **kwargs: _fake_round(),
    )
    launched = client.post("/api/profile/interview")
    assert launched.status_code == 202
    run_id = launched.json()["runId"]
    run = None
    for _ in range(50):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in {"done", "error"}:
            break
        time.sleep(0.02)
    assert run is not None
    assert run["state"] == "done"
    return run_id


def test_interview_requires_primary_and_both_model_keys(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(profile_router, "resolve_api_key", lambda model: "key")
    with client:
        missing_primary = client.post("/api/profile/interview")
        assert missing_primary.status_code == 400

        _seed_primary(client)
        app = cast(FastAPI, client.app)
        monkeypatch.setattr(
            profile_router,
            "resolve_api_key",
            lambda model: (
                "" if model == app.state.settings.cheap_model else "key"
            ),
        )
        missing_key = client.post("/api/profile/interview")
    assert missing_key.status_code == 400
    assert "cheap" in missing_key.json()["error"]["message"].lower()


def test_answers_history_and_conflict(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_router, "resolve_api_key", lambda model: "key")
    client = _client(tmp_path)
    with client:
        _seed_primary(client)
        run_id = _launch_and_wait(client, monkeypatch)
        profile_dir = tmp_path / "data" / "profile"
        from resume_agent.profile.interview import (
            InterviewQuestion,
            InterviewRound,
            append_round,
        )

        append_round(
            profile_dir,
            "round-1",
            run_id,
            InterviewRound(
                questions=[
                    InterviewQuestion(
                        id="q1",
                        gap="Acme impact",
                        question_text="What measurable impact did you have?",
                    )
                ]
            ),
        )
        body = {
            "answers": [{"questionId": "q1", "text": "Cut costs by 30%."}],
            "build": False,
        }
        first = client.post(f"/api/profile/interview/{run_id}/answers", json=body)
        second = client.post(f"/api/profile/interview/{run_id}/answers", json=body)
        history = client.get("/api/profile/interview/history")

    assert first.status_code == 200
    assert first.json()["buildStarted"] is False
    assert first.json()["buildSkippedReason"] == "build=false"
    assert second.status_code == 409
    assert history.status_code == 200
    assert (
        history.json()["rounds"][0]["answers"][0]["answerText"] == "Cut costs by 30%."
    )


def test_answer_auto_build_only_swallows_busy_conflicts(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_router, "resolve_api_key", lambda model: "key")
    client = _client(tmp_path)
    with client:
        _seed_primary(client)
        run_id = _launch_and_wait(client, monkeypatch)
        from resume_agent.profile.interview import (
            InterviewQuestion,
            InterviewRound,
            append_round,
        )

        append_round(
            tmp_path / "data" / "profile",
            "round-1",
            run_id,
            InterviewRound(
                questions=[InterviewQuestion(id="q1", question_text="Evidence?")]
            ),
        )
        monkeypatch.setattr(
            profile_router.profile_build,
            "run_corpus_build",
            lambda reporter, **kwargs: {"experiences": 1},
        )
        response = client.post(
            f"/api/profile/interview/{run_id}/answers",
            json={"answers": [{"questionId": "q1", "text": "Evidence."}]},
        )

    assert response.status_code == 200
    assert response.json()["buildStarted"] is True
    assert response.json()["buildRunId"]
