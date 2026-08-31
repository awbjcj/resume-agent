from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


def _client() -> TestClient:
    # In-memory sqlite keeps create_app in single-tenant mode (no admin
    # bootstrap / session auth), matching every other plain API test.
    return TestClient(create_app(db_url="sqlite://"))


def test_redo_rejects_empty_job_ids():
    with _client() as client:
        response = client.post("/api/redo", json={"jobIds": [], "stages": ["tailor"]})
    assert response.status_code == 422


def test_redo_rejects_empty_stages():
    with _client() as client:
        response = client.post("/api/redo", json={"jobIds": [1], "stages": []})
    assert response.status_code == 422


def test_redo_rejects_an_unknown_stage():
    with _client() as client:
        response = client.post(
            "/api/redo", json={"jobIds": [1], "stages": ["teleport"]}
        )
    assert response.status_code == 422


def test_redo_dedupes_repeated_ids_and_stages():
    from resume_tailor_harness.api.schemas.runs import RedoParams

    params = RedoParams(job_ids=[3, 3, 1], stages=["tailor", "tailor"])

    assert params.job_ids == [3, 1]  # order preserved, duplicates dropped
    assert params.stages == ["tailor"]


def test_redo_returns_202_with_a_run():
    with _client() as client:
        response = client.post("/api/redo", json={"jobIds": [1], "stages": ["tailor"]})
    assert response.status_code == 202
    assert response.json()["kind"] == "redo"
