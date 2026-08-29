from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(db_url="sqlite://"))


def _job(client: TestClient, company: str = "Acme") -> int:
    return client.post(
        "/api/jobs", json={"jdText": f"{company} x", "company": company, "title": "SWE"}
    ).json()["id"]


def _event(client: TestClient, job_id: int, kind: str, day: int, **over):
    body = {"kind": kind, "occurredAt": f"2026-03-{day:02d}T12:00:00Z"}
    body.update(over)
    response = client.post(f"/api/jobs/{job_id}/events", json=body)
    assert response.status_code == 201, response.text


def test_existing_analytics_contract_and_empty_timeline_contract():
    client = _client()
    with client:
        assert set(client.get("/api/analytics").json()) == {"bySource", "byBand"}
        body = client.get("/api/analytics/timeline").json()
    assert body == {"flows": [], "cycleTimes": [], "activePipeline": [], "offers": []}


def test_timeline_endpoint_returns_flow_cycle_pipeline_and_offer_payloads():
    client = _client()
    with client:
        live = _job(client, "Live")
        _event(client, live, "application_submitted", 3)
        _event(client, live, "recruiter_screen", 7)
        offer = _job(client, "OfferCo")
        _event(
            client,
            offer,
            "offer_received",
            20,
            compBase=180_000,
            compBonus=27_000,
            compEquityAnnual=60_000,
            compSigning=25_000,
            compCurrency="USD",
        )
        dead = _job(client, "Dead")
        _event(client, dead, "rejected", 10)
        body = client.get("/api/analytics/timeline").json()
    assert next(
        flow for flow in body["flows"] if flow["source"] == "application_submitted"
    ) == {
        "source": "application_submitted",
        "target": "recruiter_screen",
        "count": 1,
    }
    assert body["cycleTimes"][0]["medianDays"] == 4
    assert body["cycleTimes"][0]["sampleSize"] == 1
    assert {lane["company"] for lane in body["activePipeline"]} == {"Live", "OfferCo"}
    assert "Dead" not in {lane["company"] for lane in body["activePipeline"]}
    assert body["offers"][0]["totalComp"] == 292_000
    assert body["offers"][0]["compBase"] == 180_000


def test_timeline_endpoint_returns_every_compensated_offer_newest_first():
    client = _client()
    with client:
        job_id = _job(client, "Negotiated")
        _event(client, job_id, "offer_received", 20, sequence=1, compBase=100_000)
        _event(client, job_id, "offer_received", 25, sequence=2, compBase=120_000)
        _event(client, job_id, "offer_received", 27, sequence=3)
        offers = client.get("/api/analytics/timeline").json()["offers"]

    assert [offer["totalComp"] for offer in offers] == [120_000, 100_000]
    assert [offer["sequence"] for offer in offers] == [2, 1]
