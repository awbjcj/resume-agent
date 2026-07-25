from fastapi import FastAPI
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.services.errors import StageFailure, record_error, record_job_failure


def _app() -> FastAPI:
    return create_app(db_url="sqlite://")


def test_job_record_exposes_typed_details():
    app = _app()
    with TestClient(app) as client:
        from sqlmodel import Session

        from resume_agent.tracking.repository import save_job
        from resume_agent.tracking.tables import Job

        engine = app.state.engine
        with Session(engine) as session:
            job = save_job(
                session,
                Job(source="manual", jd_text="jd", company="Acme", title="Staff"),
            )
            job_id = job.id
            record_job_failure(
                session,
                job=job,
                stage="tailor",
                failure=StageFailure(
                    error_type="ValueError", message="boom", traceback_tail="tb"
                ),
                model="openai:gpt-5",
            )

        response = client.get("/api/errors", params={"status": "open"})

    assert response.status_code == 200
    record = response.json()["records"][0]
    details = record["jobDetails"]
    assert details["jobId"] == job_id
    assert details["company"] == "Acme"
    assert details["stage"] == "tailor"
    assert details["errorType"] == "ValueError"
    assert details["model"] == "openai:gpt-5"
    assert details["tracebackTail"] == "tb"


def test_source_record_has_no_job_details():
    app = _app()
    with TestClient(app) as client:
        from sqlmodel import Session

        with Session(app.state.engine) as session:
            record_error(
                session, kind="source", source_label="workday:acme", message="HTTP 500"
            )

        response = client.get("/api/errors", params={"status": "open"})

    assert response.json()["records"][0]["jobDetails"] is None


def test_unparseable_details_yield_none_not_500():
    app = _app()
    with TestClient(app) as client:
        from sqlmodel import Session

        with Session(app.state.engine) as session:
            record_error(
                session,
                kind="job",
                source_label="job:1:tailor",
                message="legacy",
                details={"totally": "different shape"},
            )

        response = client.get("/api/errors", params={"status": "open"})

    assert response.status_code == 200
    assert response.json()["records"][0]["jobDetails"] is None


def test_errors_list_paginates():
    app = _app()
    with TestClient(app) as client:
        from sqlmodel import Session

        with Session(app.state.engine) as session:
            for index in range(7):
                record_error(
                    session, kind="source", source_label=f"workday:acme-{index}",
                    message="HTTP 500",
                )

        response = client.get(
            "/api/errors", params={"status": "open", "page": 2, "pageSize": 3}
        )

    body = response.json()
    assert len(body["records"]) == 3
    assert body["pagination"]["page"] == 2
    assert body["pagination"]["pageSize"] == 3
    assert body["pagination"]["totalItems"] == 7
    assert body["pagination"]["totalPages"] == 3
