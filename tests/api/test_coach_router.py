import io
import time

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import coach as coach_router
from resume_agent.profile.coach_store import (
    CoachDraftNote,
    CoachTopic,
    CoachTurnRecord,
    apply_turn_delta,
    create_session,
)


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


def _seed_draft(tmp_path, sid="s1"):
    profile_dir = tmp_path / "data" / "profile"
    create_session(
        profile_dir,
        sid,
        [CoachTopic(id="t1", gap="Acme impact")],
        CoachTurnRecord(role="coach", kind="question", text="First?", topic_id="t1"),
    )
    apply_turn_delta(
        profile_dir,
        sid,
        user_text="I cut deploy time 40%.",
        coach_turn=CoachTurnRecord(role="coach", kind="draft_note", text="Draft.", topic_id="t1"),
        new_topics=[],
        skipped_topic_ids=[],
        draft=CoachDraftNote(
            topic_id="t1",
            title="Acme deploys",
            summary="Cut deploy time 40%.",
            quotes=["I cut deploy time 40%."],
        ),
    )


def _wait(client, run_id):
    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in {"done", "error"}:
            return run
        time.sleep(0.02)
    raise AssertionError("run never finished")


def _view(sid="s1", status="active"):
    return {
        "sessionId": sid,
        "startedAt": "2026-07-15T00:00:00+00:00",
        "endedAt": None,
        "status": status,
        "turns": [],
        "topics": [],
        "draftNotes": [],
        "recap": None,
        "impact": None,
    }


def test_start_guards_and_opening_run(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(coach_router, "resolve_api_key", lambda model: "key")
    with client:
        assert client.post("/api/profile/coach/sessions").status_code == 400
        _seed_primary(client)
        monkeypatch.setattr(coach_router, "run_opening_turn", lambda reporter, **kwargs: _view())
        response = client.post("/api/profile/coach/sessions")
        assert response.status_code == 202
        assert _wait(client, response.json()["runId"])["state"] == "done"


def test_session_fetch_message_and_unknown_mapping(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(coach_router, "resolve_api_key", lambda model: "key")
    with client:
        _seed_primary(client)
        _seed_draft(tmp_path)
        assert client.get("/api/profile/coach/sessions/s1").status_code == 200
        assert client.get("/api/profile/coach/sessions/nope").status_code == 404
        monkeypatch.setattr(coach_router, "run_message_turn", lambda reporter, **kwargs: _view())
        sent = client.post("/api/profile/coach/sessions/s1/messages", json={"message": "hi"})
        assert sent.status_code == 202
        assert _wait(client, sent.json()["runId"])["state"] == "done"


def test_note_save_discard_and_conflicts(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(coach_router, "resolve_api_key", lambda model: "key")
    with client:
        _seed_primary(client)
        _seed_draft(tmp_path)
        body = {
            "title": "Acme deploys",
            "summary": "Cut deploy time 40%.",
            "quotes": ["I cut deploy time 40%."],
        }
        saved = client.post("/api/profile/coach/sessions/s1/notes/t1", json=body)
        assert saved.status_code == 200 and saved.json()["docId"]
        assert client.post("/api/profile/coach/sessions/s1/notes/t1", json=body).status_code == 409

        # A separate pending draft exercises DELETE.
        from resume_agent.profile.coach_store import end_session

        end_session(tmp_path / "data" / "profile", "s1", "done")
        create_session(
            tmp_path / "data" / "profile",
            "s2",
            [CoachTopic(id="t1", gap="g")],
            CoachTurnRecord(role="coach", kind="question", text="q", topic_id="t1"),
        )
        apply_turn_delta(
            tmp_path / "data" / "profile",
            "s2",
            user_text="evidence",
            coach_turn=CoachTurnRecord(role="coach", kind="draft_note", text="d", topic_id="t1"),
            new_topics=[],
            skipped_topic_ids=[],
            draft=CoachDraftNote(topic_id="t1", title="T", summary="S", quotes=["evidence"]),
        )
        discarded = client.delete("/api/profile/coach/sessions/s2/notes/t1")
        assert discarded.status_code == 200
        assert discarded.json()["draftNotes"][0]["status"] == "discarded"


def test_end_run_returns_nested_build_id(monkeypatch, tmp_path):
    client = _client(tmp_path)
    monkeypatch.setattr(coach_router, "resolve_api_key", lambda model: "key")
    with client:
        _seed_primary(client)
        _seed_draft(tmp_path)
        body = {
            "title": "Acme",
            "summary": "Cut deploy time 40%.",
            "quotes": ["I cut deploy time 40%."],
        }
        assert client.post("/api/profile/coach/sessions/s1/notes/t1", json=body).status_code == 200
        ended_view = _view(status="ended") | {
            "draftNotes": [{"topicId": "t1", "title": "T", "summary": "S", "quotes": ["q"], "status": "saved"}],
            "recap": "Covered Acme.",
        }
        monkeypatch.setattr(coach_router, "run_recap_turn", lambda reporter, **kwargs: ended_view)
        monkeypatch.setattr(coach_router, "run_build_with_impact", lambda reporter, **kwargs: {"impact": {}})
        response = client.post("/api/profile/coach/sessions/s1/end", json={"build": True})
        run = _wait(client, response.json()["runId"])
        assert run["state"] == "done"
        assert run["result"]["buildRunId"]
