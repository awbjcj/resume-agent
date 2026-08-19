from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resume_agent.api.routers.taxonomy as taxonomy_router
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.discovery.requirements import bind_job_requirements
from resume_agent.models.job import JobCriteria
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job


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


def test_corrects_a_typed_job_requirement_without_requiring_source_reconstruction_in_ui(client):
    jd_text = "This role requires Stakeholder orchestration."
    criteria = bind_job_requirements(
        JobCriteria(must_have_skills=["Stakeholder orchestration"]),
        job_id=1,
        jd_text=jd_text,
        taxonomy_revision="before",
    )
    requirement = criteria.typed_requirements[0]
    with get_session(client.app.state.engine) as session:
        job = save_job(
            session,
            Job(source="manual", jd_text=jd_text, criteria_json=criteria.model_dump(mode="json")),
        )
        assert job.id == 1

    response = client.patch(
        f"/api/taxonomy/jobs/1/requirements/{requirement.id}/term-type",
        json={
            "newType": "capability",
            "rationale": "Reviewed requirement semantics",
            "evidenceRefs": ["review:job:1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["conceptType"] == "capability"
    with get_session(client.app.state.engine) as session:
        stored = session.get(Job, 1)
        assert stored is not None
        rebound = JobCriteria.model_validate(stored.criteria_json)
        assert rebound.typed_requirements[0].concept_type == "capability"
