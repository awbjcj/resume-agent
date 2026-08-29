from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat().replace("+00:00", "Z")


def _job_with_event(
    client: TestClient,
    company: str,
    delta: timedelta,
    *,
    kind: str = "technical_round",
    result: str = "pending",
) -> int:
    job_id = client.post(
        "/api/jobs",
        json={"jdText": f"Work for {company}", "company": company, "title": "SWE"},
    ).json()["id"]
    response = client.post(
        f"/api/jobs/{job_id}/events",
        json={"kind": kind, "occurredAt": _iso(delta), "result": result},
    )
    assert response.status_code == 201, response.text
    return job_id


def test_dashboard_upcoming_events_are_chronological_and_bounded() -> None:
    client = TestClient(create_app(db_url="sqlite://"))
    with client:
        _job_with_event(client, "Later", timedelta(days=5))
        _job_with_event(client, "Sooner", timedelta(days=1), kind="offer_deadline")
        _job_with_event(client, "Too far", timedelta(days=30))
        _job_with_event(client, "Past", timedelta(days=-1))
        _job_with_event(client, "Cancelled", timedelta(days=2), result="cancelled")
        _job_with_event(
            client, "Unrelated", timedelta(days=2), kind="application_submitted"
        )
        body = client.get("/api/dashboard/summary").json()
    assert [entry["company"] for entry in body["upcomingEvents"]] == ["Sooner", "Later"]
    assert body["upcomingEvents"][0]["kind"] == "offer_deadline"


def test_dashboard_summary_defaults_to_an_empty_upcoming_list() -> None:
    client = TestClient(create_app(db_url="sqlite://"))
    with client:
        assert client.get("/api/dashboard/summary").json()["upcomingEvents"] == []
