from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resume_agent.api.routers.taxonomy as taxonomy_router
from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    correction_path = tmp_path / "term_type_corrections.json"
    monkeypatch.setattr(
        taxonomy_router,
        "_term_correction_path",
        lambda: correction_path,
    )
    app = create_app(db_url="sqlite://", data_dir=tmp_path / "data")
    with TestClient(app) as test_client:
        yield test_client


def test_classify_and_correct_a_term_with_server_owned_actor(client):
    source = {
        "sourceKind": "profileSkill",
        "sourceId": "skill:leadership",
        "originalText": "Leadership",
    }
    classified = client.post("/api/taxonomy/term-types:classify", json=source)

    assert classified.status_code == 200
    decision = classified.json()
    assert decision["conceptType"] == "unknown"
    assert decision["originalText"] == "Leadership"

    corrected = client.patch(
        f"/api/taxonomy/term-types/{decision['id']}",
        json={
            "source": source,
            "newType": "capability",
            "rationale": "Reviewed candidate evidence",
            "evidenceRefs": ["exp:1:bullet:2"],
        },
    )

    assert corrected.status_code == 200
    payload = corrected.json()
    assert payload["conceptType"] == "capability"
    assert payload["decisionSource"] == "correction"

    events = client.get("/api/taxonomy/term-type-corrections").json()
    assert len(events) == 1
    assert events[0]["actorId"] == "local-user"
    assert events[0]["scope"] == "profile"


def test_correction_rejects_a_path_id_that_does_not_match_the_source(client):
    response = client.patch(
        "/api/taxonomy/term-types/term:not-the-source",
        json={
            "source": {
                "sourceKind": "profileSkill",
                "sourceId": "skill:leadership",
                "originalText": "Leadership",
            },
            "newType": "capability",
            "rationale": "Reviewed",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TERM_DECISION_MISMATCH"


def test_invalid_type_is_rejected_by_the_wire_schema(client):
    response = client.patch(
        "/api/taxonomy/term-types/term:any",
        json={
            "source": {
                "sourceKind": "profileSkill",
                "sourceId": "skill:leadership",
                "originalText": "Leadership",
            },
            "newType": "mystery",
            "rationale": "Reviewed",
        },
    )

    assert response.status_code == 422

