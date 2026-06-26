from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, **kw):
    with get_session(app.state.engine) as session:
        job = Job(source="manual", jd_text="x", **kw)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_pipeline_returns_paginated_envelope():
    client = _client()
    with client:  # triggers lifespan -> engine
        _seed(client.app, status=JobStatus.tailored.value, fit_score=80, company="Acme")
        resp = client.get("/api/pipeline?pageSize=10")
        body = resp.json()
    assert resp.status_code == 200
    assert body["pagination"]["pageSize"] == 10
    assert body["data"][0]["company"] == "Acme"
    assert "fitScore" in body["data"][0]
    assert body["total"] == 1
    assert body["facets"]["status"]["tailored"] == 1


def test_pipeline_status_filter():
    client = _client()
    with client:
        _seed(client.app, status=JobStatus.tailored.value, company="Keep")
        _seed(client.app, status=JobStatus.raw.value, company="Drop")
        body = client.get("/api/pipeline?status=tailored").json()
    assert [r["company"] for r in body["data"]] == ["Keep"]


def test_triage_archived_query():
    client = _client()
    with client:
        body = client.get("/api/triage?archived=true").json()
    assert body["data"] == []


def test_bearer_enforced_on_guarded_route():
    client = TestClient(create_app(db_url="sqlite://", api_token="secret"))
    with client:
        assert client.get("/api/pipeline").status_code == 401
        ok = client.get("/api/pipeline", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200


def test_shortlist_item_exposes_facet_fields():
    client = _client()
    with client:
        _seed(
            client.app,
            status=JobStatus.shortlisted.value,
            fit_score=70,
            company="Acme",
            location="New York, NY, US",
        )
        body = client.get("/api/shortlist").json()
    assert body["data"], "expected one shortlisted row"
    item = body["data"][0]
    for key in (
        "locationCountry",
        "locationRegion",
        "locationCity",
        "sicMajor",
        "sicDivision",
        "sicLabel",
    ):
        assert key in item
