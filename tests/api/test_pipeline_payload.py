from fastapi.testclient import TestClient
from sqlmodel import select

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import Job, JobStatus


def test_pipeline_uses_bounded_previews_but_detail_keeps_full_description():
    client = TestClient(create_app(db_url="sqlite://"))
    description = "Build reliable distributed systems with Python. " * 130
    with client:
        with get_session(client.app.state.engine) as session:
            for index in range(50):
                session.add(
                    Job(
                        source="manual",
                        company=f"Company {index:02d}",
                        title="Platform Engineer",
                        jd_text=description,
                        status=JobStatus.approved.value,
                        fit_score=index,
                        criteria_json={
                            "must_have_skills": ["Python"],
                            "remote_policy": "remote",
                        },
                    )
                )
            session.commit()
            first_id = session.exec(select(Job.id).order_by(Job.id)).first()

        response = client.get("/api/pipeline?pageSize=50")
        detail = client.get(f"/api/jobs/{first_id}")

    assert response.status_code == 200
    assert len(response.content) < 150_000
    rows = response.json()["data"]
    assert len(rows) == 50
    assert all("jdText" not in row for row in rows)
    assert all(len(row["jdPreview"]) <= 400 for row in rows)
    assert detail.status_code == 200
    assert detail.json()["jdText"] == description.strip()
