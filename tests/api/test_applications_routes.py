import csv
import io

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(db_url="sqlite://"))


def _job(client: TestClient, company: str = "Acme") -> int:
    return client.post(
        "/api/jobs", json={"jdText": "x", "company": company, "title": "SWE"}
    ).json()["id"]


def _event(client: TestClient, job_id: int, kind: str, day: int, **over):
    body = {"kind": kind, "occurredAt": f"2026-03-{day:02d}T12:00:00Z"}
    body.update(over)
    response = client.post(f"/api/jobs/{job_id}/events", json=body)
    assert response.status_code == 201, response.text


def test_grid_returns_keyed_cells_and_display_overflow():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "application_submitted", 1)
        for sequence in range(1, 10):
            _event(client, job_id, "technical_round", sequence + 1, sequence=sequence)
        body = client.get("/api/applications").json()
    assert body["technicalRoundColumns"] == 6
    assert body["rows"][0]["overflowRounds"] == 3
    assert "application_submitted" in body["rows"][0]["cells"]


def test_wide_csv_is_uncapped_and_long_csv_has_one_row_per_event():
    client = _client()
    with client:
        job_id = _job(client)
        for sequence in range(1, 10):
            _event(client, job_id, "technical_round", sequence, sequence=sequence)
        wide = client.get("/api/applications.csv?shape=wide")
        long = client.get("/api/applications.csv?shape=long")
    assert wide.status_code == 200
    assert wide.headers["content-type"].startswith("text/csv")
    assert "attachment" in wide.headers["content-disposition"]
    wide_rows = list(csv.DictReader(io.StringIO(wide.text)))
    assert len(wide_rows) == 1
    assert "technical_round_9" in wide_rows[0]
    long_rows = list(csv.DictReader(io.StringIO(long.text)))
    assert len(long_rows) == 9
    assert {row["sequence"] for row in long_rows} == {
        str(value) for value in range(1, 10)
    }


def test_unknown_shape_is_422_and_empty_csv_is_header_only():
    client = _client()
    with client:
        assert client.get("/api/applications.csv?shape=sideways").status_code == 422
        assert client.get("/api/applications").json()["rows"] == []
        csv_text = client.get("/api/applications.csv?shape=wide").text
    assert len(csv_text.strip().splitlines()) == 1


def test_long_csv_preserves_zero_compensation_values():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "offer_received", 9, compBase=0, compBonus=0)
        response = client.get("/api/applications.csv?shape=long")

    row = next(csv.DictReader(io.StringIO(response.text)))
    assert row["comp_base"] == "0"
    assert row["comp_bonus"] == "0"


def test_csv_neutralizes_formula_cells_and_wide_includes_terminal_events():
    client = _client()
    with client:
        job_id = _job(client, '=HYPERLINK("https://evil.test")')
        _event(client, job_id, "rejected", 11, notes="+cmd|' /C calc'!A0")
        wide = next(
            csv.DictReader(io.StringIO(client.get("/api/applications.csv").text))
        )
        long = next(
            csv.DictReader(
                io.StringIO(client.get("/api/applications.csv?shape=long").text)
            )
        )

    assert wide["company"].startswith("'=")
    assert wide["rejected"] == "2026-03-11T12:00:00Z"
    assert long["notes"].startswith("'+")
