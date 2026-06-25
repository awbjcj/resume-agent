from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, **kw):
    with get_session(app.state.engine) as s:
        source = kw.pop("source", "manual")
        job = Job(source=source, jd_text="x", **kw)
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def test_patch_status_approves():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.shortlisted.value)
        resp = client.patch(f"/api/jobs/{jid}", json={"status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_patch_archived_then_restore():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.raw.value)
        archived = client.patch(f"/api/jobs/{jid}", json={"archived": True}).json()
        assert archived["archivedAt"] is not None
        restored = client.patch(f"/api/jobs/{jid}", json={"archived": False}).json()
        assert restored["archivedAt"] is None


def test_delete_conflict_when_has_progress():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.rendered.value)
        resp = client.delete(f"/api/jobs/{jid}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_delete_succeeds_zero_progress():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.raw.value)
        assert client.delete(f"/api/jobs/{jid}").status_code == 204


def test_put_application_upserts():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.rendered.value)
        resp = client.put(
            f"/api/jobs/{jid}/application", json={"status": "submitted", "notes": "ref"}
        )
        body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "submitted"
    assert body["notes"] == "ref"


def test_post_manual_job_creates():
    client = _client()
    with client:
        resp = client.post("/api/jobs", json={"jdText": "Need a dev", "company": "Acme"})
    assert resp.status_code == 201
    assert resp.json()["company"] == "Acme"
