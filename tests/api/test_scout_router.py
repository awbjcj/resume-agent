import time

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import scout as scout_router
from resume_agent.discovery.scout_store import (
    ScoutProposal,
    ScoutTurnRecord,
    TermPayload,
    create_session_from_turn,
    end_session,
)


def client_for(tmp_path):
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


def wait_for_run(client, run_id):
    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in {"done", "error", "cancelled"}:
            return run
        time.sleep(0.02)
    raise AssertionError("run never finished")


def seed(tmp_path, *, ended=False):
    root = tmp_path / "data"
    create_session_from_turn(
        root,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="search_term",
                term=TermPayload(value="inference serving"),
                check="new",
            )
        ],
    )
    if ended:
        end_session(root, "s1", "Done")


def test_start_preallocates_session_metadata_and_launches_stream(monkeypatch, tmp_path):
    client = client_for(tmp_path)
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda model: "key")
    monkeypatch.setattr(scout_router, "run_start_turn", lambda reporter, **kwargs: {})
    with client:
        response = client.post("/api/scout/sessions", json={"message": "AI infra"})
        assert response.status_code == 202
        body = response.json()
        assert body["kind"] == "scout-start"
        assert body["meta"] == {
            "stream": True,
            "sessionId": body["meta"]["sessionId"],
            "turnCount": 0,
        }
        assert wait_for_run(client, body["runId"])["state"] == "done"


def test_detail_list_message_and_end_metadata(monkeypatch, tmp_path):
    client = client_for(tmp_path)
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda model: "key")
    monkeypatch.setattr(scout_router, "run_message_turn", lambda reporter, **kwargs: {})
    monkeypatch.setattr(scout_router, "run_recap_turn", lambda reporter, **kwargs: {})
    with client:
        seed(tmp_path)
        assert client.get("/api/scout/sessions/s1").status_code == 200
        assert client.get("/api/scout/sessions/nope").status_code == 404
        assert client.get("/api/scout/sessions").json()["sessions"][0]["sessionId"] == "s1"
        sent = client.post("/api/scout/sessions/s1/messages", json={"message": "smaller"})
        assert sent.status_code == 202
        assert sent.json()["meta"]["turnCount"] == 2
        wait_for_run(client, sent.json()["runId"])
        ended = client.post("/api/scout/sessions/s1/end")
        assert ended.status_code == 202
        assert ended.json()["meta"]["sessionId"] == "s1"


def test_ended_session_blocks_messages_but_allows_pending_resolution(tmp_path):
    client = client_for(tmp_path)
    with client:
        seed(tmp_path, ended=True)
        assert client.post("/api/scout/sessions/s1/messages", json={"message": "more"}).status_code == 409
        approved = client.post("/api/scout/sessions/s1/proposals/p1/approve")
        assert approved.status_code == 200
        assert approved.json()["proposals"][0]["status"] == "added"


def test_dismiss_validation_and_lifecycle(tmp_path):
    client = client_for(tmp_path)
    with client:
        seed(tmp_path)
        assert client.post(
            "/api/scout/sessions/s1/proposals/p1/dismiss",
            json={"reason": "x" * 201},
        ).status_code == 422
        dismissed = client.post(
            "/api/scout/sessions/s1/proposals/p1/dismiss", json={"reason": "not relevant"}
        )
        assert dismissed.status_code == 200
        end_session(tmp_path / "data", "s1", "Done")
        assert client.post("/api/scout/sessions/s1/archive").status_code == 200
        assert client.get("/api/scout/sessions").json()["sessions"] == []
        assert client.get("/api/scout/sessions", params={"includeArchived": True}).json()["sessions"]
        assert client.post("/api/scout/sessions/s1/unarchive").status_code == 200
        deleted = client.delete("/api/scout/sessions/s1")
        assert deleted.status_code == 204 and deleted.content == b""


def test_legacy_discovery_routes_are_removed(tmp_path):
    client = client_for(tmp_path)
    with client:
        assert client.post("/api/sources/discover", json={"prompt": "AI infra"}).status_code == 405
        assert client.post("/api/search/discover", json={"prompt": "AI infra"}).status_code == 405
