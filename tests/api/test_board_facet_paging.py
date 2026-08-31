from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import Job, JobStatus


def test_pipeline_facets_are_only_returned_on_first_page():
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            session.add_all(
                [
                    Job(
                        source="manual",
                        jd_text="x",
                        company=f"Company {index}",
                        status=JobStatus.tailored.value,
                    )
                    for index in range(3)
                ]
            )
            session.commit()

        first = client.get("/api/pipeline?page=1&pageSize=1").json()
        second = client.get("/api/pipeline?page=2&pageSize=1").json()

    assert first["facets"]["status"]["tailored"] == 3
    assert second["facets"] is None
    assert first["pagination"]["totalItems"] == 3
    assert second["pagination"]["totalItems"] == 3
    assert len(first["data"]) == len(second["data"]) == 1
