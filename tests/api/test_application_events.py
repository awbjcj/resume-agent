from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(db_url="sqlite://"))


def _job(client: TestClient, company: str = "Acme") -> int:
    response = client.post(
        "/api/jobs",
        json={"jdText": f"Build things for {company}.", "company": company, "title": "SWE"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_create_list_update_and_delete_event() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        created = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "technical_round",
                "occurredAt": "2026-03-09T19:00:00Z",
                "timezone": "America/New_York",
                "durationMinutes": 60,
                "modality": "virtual",
                "platform": "zoom",
                "notes": "LRU cache",
            },
        )
        assert created.status_code == 201, created.text
        event_id = created.json()["id"]
        assert created.json()["sequence"] == 1
        assert client.get(f"/api/jobs/{job_id}/events").json()[0]["id"] == event_id

        updated = client.patch(
            f"/api/jobs/{job_id}/events/{event_id}",
            json={"result": "advanced", "reflection": "Clarified constraints"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["result"] == "advanced"
        assert updated.json()["reflection"] == "Clarified constraints"

        assert client.delete(f"/api/jobs/{job_id}/events/{event_id}").status_code == 204
        assert client.get(f"/api/jobs/{job_id}/events").json() == []


def test_event_advances_application_status() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        response = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "application_submitted",
                "occurredAt": "2026-03-03T12:00:00Z",
            },
        )
        assert response.status_code == 201, response.text
        assert client.get(f"/api/jobs/{job_id}").json()["application"]["status"] == "submitted"


def test_offer_response_derives_total_compensation() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        body = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "offer_received",
                "occurredAt": "2026-03-20T12:00:00Z",
                "compBase": 180000,
                "compBonus": 27000,
                "compEquityAnnual": 60000,
                "compSigning": 25000,
                "compCurrency": "USD",
            },
        ).json()
        assert body["totalComp"] == 292000


def test_invalid_event_payloads_use_the_api_validation_envelope() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        for payload in (
            {"kind": "vibe_check", "occurredAt": "2026-03-03T12:00:00Z"},
            {"kind": "behavioral"},
            {"kind": "custom"},
        ):
            response = client.post(f"/api/jobs/{job_id}/events", json=payload)
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_event_ids_are_scoped_to_the_job_in_mutation_routes() -> None:
    client = _client()
    with client:
        first_job = _job(client, "First")
        second_job = _job(client, "Second")
        event_id = client.post(
            f"/api/jobs/{first_job}/events",
            json={"kind": "behavioral", "occurredAt": "2026-03-09T19:00:00Z"},
        ).json()["id"]

        assert (
            client.patch(
                f"/api/jobs/{second_job}/events/{event_id}", json={"notes": "wrong job"}
            ).status_code
            == 404
        )
        assert client.delete(f"/api/jobs/{second_job}/events/{event_id}").status_code == 404


def test_missing_job_and_event_are_404() -> None:
    client = _client()
    with client:
        assert client.get("/api/jobs/9999/events").status_code == 404
        job_id = _job(client)
        assert (
            client.patch(f"/api/jobs/{job_id}/events/9999", json={"notes": "x"}).status_code
            == 404
        )


def test_offset_datetime_is_normalized_to_utc_and_naive_input_is_rejected() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        created = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "technical_round",
                "occurredAt": "2026-03-09T14:00:00-05:00",
                "timezone": "America/New_York",
            },
        )
        naive = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "technical_round", "occurredAt": "2026-03-09T14:00:00"},
        )

    assert created.status_code == 201
    assert created.json()["occurredAt"] == "2026-03-09T19:00:00Z"
    assert naive.status_code == 422


def test_patch_rejects_null_for_non_nullable_event_fields() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        event_id = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "technical_round", "occurredAt": "2026-03-09T19:00:00Z"},
        ).json()["id"]
        for field in ("kind", "allDay", "result"):
            response = client.patch(
                f"/api/jobs/{job_id}/events/{event_id}", json={field: None}
            )
            assert response.status_code == 422, (field, response.text)


def test_patch_null_sequence_clears_the_manual_override() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        event_id = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "technical_round",
                "occurredAt": "2026-03-09T19:00:00Z",
                "sequence": 9,
            },
        ).json()["id"]
        response = client.patch(
            f"/api/jobs/{job_id}/events/{event_id}", json={"sequence": None}
        )

    assert response.status_code == 200, response.text
    assert response.json()["sequence"] == 1
    assert response.json()["sequenceOverride"] is None


def test_auto_sequence_reorders_earlier_rounds_and_manual_sequence_is_preserved() -> None:
    client = _client()
    with client:
        job_id = _job(client)
        later = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "technical_round", "occurredAt": "2026-03-20T19:00:00Z"},
        ).json()
        earlier = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "technical_round", "occurredAt": "2026-03-10T19:00:00Z"},
        ).json()
        manual = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "technical_round",
                "occurredAt": "2026-03-25T19:00:00Z",
                "sequence": 9,
            },
        ).json()
        invalid = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "technical_round",
                "occurredAt": "2026-03-26T19:00:00Z",
                "sequence": 0,
            },
        )
        events = client.get(f"/api/jobs/{job_id}/events").json()

    by_id = {event["id"]: event for event in events}
    assert by_id[earlier["id"]]["sequence"] == 1
    assert by_id[later["id"]]["sequence"] == 2
    assert manual["sequence"] == 9
    assert invalid.status_code == 422
