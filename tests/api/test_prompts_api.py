"""Prompt transparency exposes immutable rules and edits guidance only."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config")
    with TestClient(app) as test_client:
        yield test_client


def test_get_lists_complete_prompt_contract(client) -> None:
    response = client.get("/api/agents/prompts")
    assert response.status_code == 200
    by_key = {item["key"]: item for item in response.json()}
    assert "tailor-writer" in by_key
    assert "reviewer-merged-advisory" in by_key
    assert "email-classifier" in by_key
    assert by_key["tailor-writer"]["guidance"] is None
    assert by_key["reviewer-fact-check"]["editable"] is False
    assert by_key["tailor-writer"]["instructions"]


def test_put_round_trips_and_clears_guidance(client) -> None:
    response = client.put(
        "/api/agents/prompts/coach", json={"guidance": "Ask about open source."}
    )
    assert response.status_code == 200
    assert response.json()["guidance"] == "Ask about open source."
    listed = client.get("/api/agents/prompts").json()
    assert next(item for item in listed if item["key"] == "coach")["guidance"] == (
        "Ask about open source."
    )
    cleared = client.put("/api/agents/prompts/coach", json={"guidance": ""})
    assert cleared.status_code == 200
    assert cleared.json()["guidance"] is None


def test_put_error_contracts(client) -> None:
    unknown = client.put("/api/agents/prompts/nope", json={"guidance": "x"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "unknown_agent"

    locked = client.put(
        "/api/agents/prompts/reviewer-fact-check", json={"guidance": "Be lenient."}
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "agent_not_editable"

    over_cap = client.put("/api/agents/prompts/coach", json={"guidance": "x" * 4001})
    assert over_cap.status_code == 422
    assert over_cap.json()["error"]["code"] == "VALIDATION_ERROR"
