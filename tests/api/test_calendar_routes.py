from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(db_url="sqlite://"))


def _job(client: TestClient, company: str) -> int:
    return client.post(
        "/api/jobs",
        json={"jdText": f"Work for {company}", "company": company, "title": "SWE"},
    ).json()["id"]


def _event(client: TestClient, job_id: int, **over) -> int:
    body = {
        "kind": "technical_round",
        "occurredAt": "2027-03-09T19:00:00Z",
        "durationMinutes": 60,
        "platform": "zoom",
        "locationOrLink": "https://zoom.us/j/123",
    }
    body.update(over)
    response = client.post(f"/api/jobs/{job_id}/events", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_single_event_and_upcoming_calendar_downloads() -> None:
    client = _client()
    with client:
        job_id = _job(client, "Acme")
        event_id = _event(client, job_id)
        single = client.get(f"/api/jobs/{job_id}/events/{event_id}.ics")
        upcoming = client.get("/api/applications/upcoming.ics")
    assert single.status_code == 200
    assert single.headers["content-type"].startswith("text/calendar")
    assert "attachment" in single.headers["content-disposition"]
    assert "BEGIN:VEVENT" in single.text
    assert "TRIGGER:-PT60M" in single.text
    assert upcoming.status_code == 200
    assert "BEGIN:VCALENDAR" in upcoming.text


def test_event_download_is_scoped_to_its_job() -> None:
    client = _client()
    with client:
        first = _job(client, "First")
        second = _job(client, "Second")
        event_id = _event(client, first)
        assert client.get(f"/api/jobs/{second}/events/{event_id}.ics").status_code == 404


def test_undated_custom_event_cannot_be_exported() -> None:
    client = _client()
    with client:
        job_id = _job(client, "Acme")
        event_id = _event(
            client,
            job_id,
            kind="custom",
            customLabel="Referral ping",
            occurredAt=None,
        )
        response = client.get(f"/api/jobs/{job_id}/events/{event_id}.ics")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_offset_api_input_exports_the_same_named_timezone_instant() -> None:
    client = _client()
    with client:
        job_id = _job(client, "Acme")
        event_id = _event(
            client,
            job_id,
            occurredAt="2026-03-09T14:00:00-05:00",
            timezone="America/New_York",
        )
        calendar = client.get(f"/api/jobs/{job_id}/events/{event_id}.ics").text

    assert "DTSTART;TZID=America/New_York:20260309T150000" in calendar
