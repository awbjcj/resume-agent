from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import Application, Job


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def test_comparison_endpoint_validates_selection_and_preserves_order(tmp_path):
    client = TestClient(create_app(db_url="sqlite://", runs_root=tmp_path))
    with client:
        with get_session(_app(client).state.engine) as session:
            jobs = [
                Job(source="manual", company="Acme", title="Platform Engineer", fit_score=90),
                Job(source="manual", company="Globex", title="Staff Engineer", fit_score=81),
            ]
            session.add_all(jobs)
            session.commit()
            for job in jobs:
                session.refresh(job)
                assert job.id is not None
                session.add(Application(job_id=job.id, status="interview"))
            session.commit()
            ids = [job.id for job in jobs]
        response = client.post(
            "/api/jobs/company-intelligence-comparisons",
            json={"jobIds": [ids[1], ids[0]]},
        )
        duplicate = client.post(
            "/api/jobs/company-intelligence-comparisons",
            json={"jobIds": [ids[0], ids[0]]},
        )
        paths = client.get("/openapi.json").json()["paths"]

    assert response.status_code == 200
    assert [item["jobId"] for item in response.json()["items"]] == [ids[1], ids[0]]
    assert response.json()["items"][0]["companyEvidence"]["state"] == "not_researched"
    assert duplicate.status_code == 422
    assert "/api/jobs/company-intelligence-comparisons" in paths


def test_comparison_endpoint_rejects_terminal_applications(tmp_path):
    client = TestClient(create_app(db_url="sqlite://", runs_root=tmp_path))
    with client:
        with get_session(_app(client).state.engine) as session:
            jobs = [
                Job(source="manual", company="Acme", title="Engineer"),
                Job(source="manual", company="Globex", title="Engineer"),
            ]
            session.add_all(jobs)
            session.commit()
            for index, job in enumerate(jobs):
                session.refresh(job)
                assert job.id is not None
                session.add(
                    Application(
                        job_id=job.id,
                        status="rejected" if index == 0 else "interview",
                    )
                )
            session.commit()
            ids = [job.id for job in jobs]
        response = client.post(
            "/api/jobs/company-intelligence-comparisons",
            json={"jobIds": ids},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMPARISON_REQUIRES_ACTIVE_ROLES"
