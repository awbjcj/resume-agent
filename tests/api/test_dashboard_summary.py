"""Status counts + action queues over a seeded DB; archived rows excluded."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.tracking.tables import Application, Job


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def _seed(engine):
    with Session(engine) as session:
        def job(status, archived=False, **kw):
            j = Job(source="manual", company="Acme", title=f"{status}-role",
                    status=status, dedup_key=f"acme|{status}{archived}", **kw)
            if archived:
                j.archived_at = datetime.now(timezone.utc)
            session.add(j)
            return j

        job("filtered")
        job("filtered", archived=True)  # must not count
        job("shortlisted")
        job("approved")
        rendered = job("rendered")
        session.commit()
        assert rendered.id is not None
        session.add(Application(job_id=rendered.id, status="submitted"))
        session.commit()


def test_summary_counts_and_queues(client):
    _seed(client.app.state.engine)
    body = client.get("/api/dashboard/summary").json()
    assert body["statusCounts"]["filtered"] == 1  # archived excluded
    assert body["queues"] == {"triage": 1, "approve": 1, "tailor": 1, "apply": 1}
    assert body["applied"] == 1


def test_applied_excludes_archived_jobs(client):
    with Session(client.app.state.engine) as session:
        archived_rendered = Job(
            source="manual", company="Acme", title="rendered-archived-role",
            status="rendered", dedup_key="acme|rendered-archived",
            archived_at=datetime.now(timezone.utc),
        )
        session.add(archived_rendered)
        session.commit()
        assert archived_rendered.id is not None
        session.add(Application(job_id=archived_rendered.id, status="submitted"))
        session.commit()

    body = client.get("/api/dashboard/summary").json()
    assert body["applied"] == 0  # the only Application belongs to an archived job
