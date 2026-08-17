from datetime import datetime, timedelta, timezone
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.tracking.tables import H1BCompanyEvidence, Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, **kw):
    with get_session(app.state.engine) as session:
        source = kw.pop("source", "manual")
        job = Job(source=source, jd_text="x", **kw)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_pipeline_returns_paginated_envelope():
    client = _client()
    with client:  # triggers lifespan -> engine
        _seed(
            client.app,
            status=JobStatus.tailored.value,
            fit_score=80,
            company="Acme",
            source="greenhouse",
            location="Boston, MA",
        )
        resp = client.get("/api/pipeline?pageSize=10")
        body = resp.json()
    assert resp.status_code == 200
    assert body["pagination"]["pageSize"] == 10
    assert body["data"][0]["company"] == "Acme"
    assert body["data"][0]["source"] == "greenhouse"
    assert body["data"][0]["location"] == "Boston, MA"
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


def test_pipeline_exposes_persisted_h1b_sponsorship_status():
    client = _client()
    now = datetime.now(timezone.utc)
    evidence = H1BSponsorshipEvidence(
        status="matched",
        normalized_company="acme",
        display_company="Acme",
        fiscal_periods=["2024"],
        filing_count=1,
        certified_count=1,
        wage_summary=None,
        source_url=None,
        data_version="fixture-v1",
        retrieved_at=now,
        expires_at=now + timedelta(days=1),
        confidence=0.7,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )
    with client:
        _seed(
            client.app,
            status=JobStatus.filtered.value,
            company="Acme",
        )
        app = cast(FastAPI, client.app)
        with get_session(app.state.engine) as session:
            session.add(
                H1BCompanyEvidence(
                    normalized_company="acme",
                    display_company=evidence.display_company,
                    status=evidence.status,
                    evidence_json=evidence.model_dump(mode="json"),
                    expires_at=evidence.expires_at,
                    retrieved_at=evidence.retrieved_at,
                )
            )
            session.commit()
        body = client.get("/api/pipeline").json()

    assert body["data"][0]["h1BSponsorshipStatus"] == "matched"


def test_pipeline_sponsorship_and_type_filters_expose_matching_details():
    client = _client()
    with client:
        _seed(
            client.app,
            status=JobStatus.filtered.value,
            company="Keep",
            criteria_json={
                "sponsorship_signal": "offered",
                "employment_type": "full_time",
            },
            reject_reason="below salary threshold",
            reject_category="filtered",
        )
        _seed(
            client.app,
            status=JobStatus.filtered.value,
            company="Drop",
            criteria_json={
                "sponsorship_signal": "denied",
                "employment_type": "contract",
            },
        )
        body = client.get(
            "/api/pipeline?sponsorship=offered&employmentType=full_time"
        ).json()

    assert [row["company"] for row in body["data"]] == ["Keep"]
    assert body["data"][0]["sponsorshipSignal"] == "offered"
    assert body["data"][0]["employmentType"] == "full_time"
    assert body["data"][0]["rejectReason"] == "below salary threshold"
    assert body["data"][0]["rejectCategory"] == "filtered"


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

    assert body["data"][0]["jdPreview"] == "Google Google San Francisco, CA Remote eligible Mid"


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
    assert item["rejectCategory"] == "filtered"


def test_triage_filters_by_reject_reason():
    client = _client()
    with client:
        _seed(
            client.app,
            status=JobStatus.rejected.value,
            company="Keep",
            reject_reason="sponsorship not available",
        )
        _seed(
            client.app,
            status=JobStatus.rejected.value,
            company="Drop",
            reject_reason="salary below minimum",
        )
        body = client.get("/api/triage?rejectReason=sponsor").json()
    assert [item["company"] for item in body["data"]] == ["Keep"]


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
            source="lever",
            location="New York, NY, US",
        )
        body = client.get("/api/shortlist").json()
    assert body["data"], "expected one shortlisted row"
    item = body["data"][0]
    assert item["source"] == "lever"
    assert item["location"] == "New York, NY, US"
    for key in (
        "locationCountry",
        "locationRegion",
        "locationCity",
    ):
        assert key in item


def test_shortlist_multi_location_filters_and_contract():
    client = _client()
    locations = [
        {"city": "Austin", "region": "TX", "country": "US", "is_us": True, "raw": "Austin, TX"},
        {"city": "Toronto", "region": "Ontario", "country": "CA", "is_us": False, "raw": "Toronto, Ontario"},
    ]
    with client:
        _seed(
            client.app,
            status=JobStatus.shortlisted.value,
            fit_score=80,
            company="Multi",
            location="Austin, TX | Toronto, Ontario",
            criteria_json={"locations": locations, "location_parts": locations[0]},
        )
        by_canada = client.get("/api/shortlist?country=CA&city=Toronto").json()
        crossed = client.get("/api/shortlist?country=CA&city=Austin").json()
        unfiltered = client.get("/api/shortlist").json()

    assert [row["company"] for row in by_canada["data"]] == ["Multi"]
    assert crossed["data"] == []
    assert by_canada["data"][0]["locations"] == [
        {"city": "Austin", "region": "TX", "country": "US", "isUs": True, "raw": "Austin, TX"},
        {"city": "Toronto", "region": "Ontario", "country": "CA", "isUs": False, "raw": "Toronto, Ontario"},
    ]
    assert by_canada["facets"]["country"] == {"CA": 1}
    assert unfiltered["facets"]["country"] == {"CA": 1, "US": 1}
