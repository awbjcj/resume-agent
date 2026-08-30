import time

from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.api.routers import scout as scout_router
from resume_agent.discovery.scout_store import (
    ScoutProposal,
    ScoutTurnRecord,
    SourcePayload,
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


def seed_unverified_source(tmp_path):
    create_session_from_turn(
        tmp_path / "data",
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="source",
                source=SourcePayload(
                    company="Acme",
                    url="https://jobs.lever.co/acme",
                    ats="lever",
                    resolution_status="unverified",
                    resolution_reason="OWNERSHIP_NOT_PROVEN",
                ),
                check="unverified",
            )
        ],
    )


def test_start_preallocates_session_metadata_and_launches_stream(monkeypatch, tmp_path):
    client = client_for(tmp_path)
    lookups = []
    monkeypatch.setattr(
        "resume_agent.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    def run_start(_reporter, **kwargs):
        lookups.append(kwargs["company_intelligence_lookup"])
        return {}

    monkeypatch.setattr(scout_router, "run_start_turn", run_start)
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
        assert len(lookups) == 1
        assert isinstance(lookups[0]._session, Session)


def test_detail_list_message_and_end_metadata(monkeypatch, tmp_path):
    client = client_for(tmp_path)
    monkeypatch.setattr(
        "resume_agent.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    monkeypatch.setattr(scout_router, "run_message_turn", lambda reporter, **kwargs: {})
    monkeypatch.setattr(scout_router, "run_recap_turn", lambda reporter, **kwargs: {})
    with client:
        seed(tmp_path)
        assert client.get("/api/scout/sessions/s1").status_code == 200
        assert client.get("/api/scout/sessions/nope").status_code == 404
        assert (
            client.get("/api/scout/sessions").json()["sessions"][0]["sessionId"] == "s1"
        )
        sent = client.post(
            "/api/scout/sessions/s1/messages", json={"message": "smaller"}
        )
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
        assert (
            client.post(
                "/api/scout/sessions/s1/messages", json={"message": "more"}
            ).status_code
            == 409
        )
        approved = client.post("/api/scout/sessions/s1/proposals/p1/approve")
        assert approved.status_code == 200
        assert approved.json()["proposals"][0]["status"] == "added"


def test_approve_body_is_optional_and_passes_manual_confirmation(monkeypatch, tmp_path):
    client = client_for(tmp_path)
    seed_unverified_source(tmp_path)
    seen = []

    def approve(root, session_id, proposal_id, **kwargs):
        seen.append(kwargs["manual_confirmation"])
        return scout_router.session_view(
            root, session_id, browser_enabled=kwargs["browser_enabled"]
        )

    monkeypatch.setattr(scout_router, "approve_proposal", approve)
    with client:
        normal = client.post("/api/scout/sessions/s1/proposals/p1/approve")
        confirmed = client.post(
            "/api/scout/sessions/s1/proposals/p1/approve",
            json={"manualConfirmation": True},
        )

    assert normal.status_code == 200
    assert confirmed.status_code == 200
    assert seen == [False, True]


def test_resolve_source_route_validates_body_and_maps_stale_changes(
    monkeypatch, tmp_path
):
    client = client_for(tmp_path)
    seed_unverified_source(tmp_path)
    seen = []

    def resolve(root, session_id, proposal_id, **kwargs):
        seen.append(kwargs["url"])
        return scout_router.session_view(
            root, session_id, browser_enabled=kwargs["browser_enabled"]
        )

    monkeypatch.setattr(scout_router, "resolve_proposal_source", resolve)
    with client:
        invalid = client.post(
            "/api/scout/sessions/s1/proposals/p1/resolve",
            json={"url": "file:///tmp/board"},
        )
        resolved = client.post(
            "/api/scout/sessions/s1/proposals/p1/resolve",
            json={"url": "https://jobs.lever.co/acme"},
        )

    assert invalid.status_code == 422
    assert resolved.status_code == 200
    assert seen == ["https://jobs.lever.co/acme"]


def test_dismiss_validation_and_lifecycle(tmp_path):
    client = client_for(tmp_path)
    with client:
        seed(tmp_path)
        assert (
            client.post(
                "/api/scout/sessions/s1/proposals/p1/dismiss",
                json={"reason": "x" * 201},
            ).status_code
            == 422
        )
        dismissed = client.post(
            "/api/scout/sessions/s1/proposals/p1/dismiss",
            json={"reason": "not relevant"},
        )
        assert dismissed.status_code == 200
        end_session(tmp_path / "data", "s1", "Done")
        renamed = client.patch(
            "/api/scout/sessions/s1", json={"title": "Healthcare search"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["sessionTitle"] == "Healthcare search"
        assert client.post("/api/scout/sessions/s1/archive").status_code == 200
        assert client.get("/api/scout/sessions").json()["sessions"] == []
        included = client.get(
            "/api/scout/sessions", params={"includeArchived": True}
        ).json()["sessions"]
        assert included[0]["sessionTitle"] == "Healthcare search"
        assert client.post("/api/scout/sessions/s1/unarchive").status_code == 200
        deleted = client.delete("/api/scout/sessions/s1")
        assert deleted.status_code == 204 and deleted.content == b""


def test_legacy_discovery_routes_are_removed(tmp_path):
    client = client_for(tmp_path)
    with client:
        assert (
            client.post(
                "/api/sources/discover", json={"prompt": "AI infra"}
            ).status_code
            == 405
        )
        assert (
            client.post("/api/search/discover", json={"prompt": "AI infra"}).status_code
            == 405
        )
