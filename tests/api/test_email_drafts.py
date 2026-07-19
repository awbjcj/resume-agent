from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as c:
        yield c


def _seed_job(client) -> int:
    from sqlmodel import Session

    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    with Session(client.app.state.engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        return job.id


def test_generate_run_and_list(client, monkeypatch):
    from resume_agent.api.routers import email_drafts as router_module

    def fake_generate(session, job_id, draft_type, instructions=None, **kwargs):
        from resume_agent.tracking.repository import save_email_draft
        from resume_agent.tracking.tables import EmailDraft

        return save_email_draft(
            session,
            EmailDraft(job_id=job_id, draft_type=draft_type, subject="s", body="b"),
        )

    monkeypatch.setattr(router_module, "generate_email_draft", fake_generate)
    monkeypatch.setattr(router_module, "_service_or_none", lambda: None)
    job_id = _seed_job(client)

    launched = client.post(
        f"/api/jobs/{job_id}/email-draft", json={"draftType": "follow_up"}
    )
    assert launched.status_code == 202

    listed = client.get(f"/api/jobs/{job_id}/email-drafts")
    assert listed.status_code == 200
    [draft] = listed.json()
    assert draft["draftType"] == "follow_up"
    assert draft["state"] == "generated"


def test_generate_rejects_unknown_type(client):
    job_id = _seed_job(client)
    response = client.post(
        f"/api/jobs/{job_id}/email-draft", json={"draftType": "spam"}
    )
    assert response.status_code == 400


def test_save_requires_connection(client):
    from sqlmodel import Session

    from resume_agent.tracking.repository import save_email_draft
    from resume_agent.tracking.tables import EmailDraft

    job_id = _seed_job(client)
    with Session(client.app.state.engine) as session:
        draft = save_email_draft(
            session,
            EmailDraft(job_id=job_id, draft_type="follow_up", subject="s", body="b"),
        )
        draft_id = draft.id
    response = client.post(f"/api/email-drafts/{draft_id}/save")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GMAIL_NOT_CONNECTED"


def test_save_creates_gmail_draft(client, monkeypatch):
    from sqlmodel import Session

    from resume_agent.api.routers import email_drafts as router_module
    from resume_agent.tracking.repository import save_email_draft
    from resume_agent.tracking.tables import EmailDraft

    created = {}

    class _Drafts:
        def create(self, userId, body):
            created["payload"] = body
            return SimpleNamespace(execute=lambda: {"id": "draft-123"})

        def update(self, userId, id, body):
            created["updated"] = id
            return SimpleNamespace(execute=lambda: {"id": id})

    class _Service:
        def users(self):
            drafts = _Drafts()
            return SimpleNamespace(drafts=lambda: drafts)

    monkeypatch.setattr(router_module, "_compose_service", lambda request: _Service())
    job_id = _seed_job(client)
    with Session(client.app.state.engine) as session:
        draft = save_email_draft(
            session,
            EmailDraft(
                job_id=job_id,
                draft_type="follow_up",
                subject="s",
                body="b",
                to_addr="jane@acme.com",
                gmail_thread_id="t1",
            ),
        )
        draft_id = draft.id

    response = client.post(f"/api/email-drafts/{draft_id}/save")
    assert response.status_code == 200
    body = response.json()
    assert body["gmailDraftId"] == "draft-123"
    assert body["state"] == "saved"
    assert created["payload"]["message"]["threadId"] == "t1"


def test_save_wraps_gmail_api_error_in_envelope(client, monkeypatch):
    from sqlmodel import Session

    from resume_agent.api.routers import email_drafts as router_module
    from resume_agent.tracking.repository import save_email_draft
    from resume_agent.tracking.tables import EmailDraft

    class _Drafts:
        def create(self, userId, body):
            def _boom():
                raise RuntimeError("HTTP 503 from Gmail")

            return SimpleNamespace(execute=_boom)

    class _Service:
        def users(self):
            drafts = _Drafts()
            return SimpleNamespace(drafts=lambda: drafts)

    monkeypatch.setattr(router_module, "_compose_service", lambda request: _Service())
    job_id = _seed_job(client)
    with Session(client.app.state.engine) as session:
        draft = save_email_draft(
            session,
            EmailDraft(job_id=job_id, draft_type="follow_up", subject="s", body="b"),
        )
        draft_id = draft.id

    response = client.post(f"/api/email-drafts/{draft_id}/save")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GMAIL_API_ERROR"
