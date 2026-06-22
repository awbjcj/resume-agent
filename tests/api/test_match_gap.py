from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_match_gap_empty_db_returns_empty_report():
    # In-memory DB has no target-status jobs, so the report is empty regardless
    # of whether a profile facts file exists on the machine.
    client = _client()
    with client:
        resp = client.get("/api/match-gap")
    assert resp.status_code == 200
    assert resp.json() == {"targetTotal": 0, "gaps": []}
