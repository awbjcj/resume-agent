from typing import cast

from fastapi import FastAPI
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


def test_pipeline_response_cleans_legacy_jd_tokens():
    client = _client()
    with client:
        app = cast(FastAPI, client.app)
        with get_session(app.state.engine) as session:
            session.add(
                Job(
                    source="google",
                    jd_text=(
                        "Google \\_corporate\\_fare\\_ Google \\_place\\_ San Francisco, CA "
                        "\\_laptop\\_windows\\_ Remote eligible \\*\\*Mid\\*\\*"
                    ),
                    status=JobStatus.approved.value,
                    company="Google",
                    title="Forward Deployed Engineer",
                )
            )
            session.commit()
        body = client.get("/api/pipeline?status=approved").json()

    assert body["data"][0]["jdText"] == "Google Google San Francisco, CA Remote eligible Mid"


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


def test_triage_item_exposes_reject_reason():
    client = _client()
    with client:
        _seed(
            client.app,
            status=JobStatus.rejected.value,
            company="Rej",
            reject_reason="salary below minimum",
            reject_category="filtered",
        )
        body = client.get("/api/triage").json()
    item = next(r for r in body["data"] if r["company"] == "Rej")
    assert item["rejectReason"] == "salary below minimum"


def test_job_detail_exposes_reject_reason():
    client = _client()
    with client:
        job_id = _seed(
            client.app,
            status=JobStatus.rejected.value,
            company="Rej",
            reject_reason="off-target role: not a match",
            reject_category="relevance",
        )
        body = client.get(f"/api/jobs/{job_id}").json()
    assert body["rejectReason"] == "off-target role: not a match"


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
    ):
        assert key in item
