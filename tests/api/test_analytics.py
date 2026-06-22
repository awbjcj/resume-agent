from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_analytics_endpoint_returns_source_and_band():
    client = _client()
    with client:
        resp = client.get("/api/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert "bySource" in body and "byBand" in body
    assert isinstance(body["bySource"], list)
    assert isinstance(body["byBand"], list)
