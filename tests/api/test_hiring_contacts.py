from concurrent.futures import Executor, Future
from types import SimpleNamespace

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import hiring_contacts as contact_router
from resume_agent.db import get_session
from resume_agent.hiring_contacts.models import (
    HiringContactDraft,
    HiringContactIntelligenceDraft,
)
from resume_agent.tracking.tables import Job


class _InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


class _Runner:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return SimpleNamespace(content=self.content)


def _client(tmp_path):
    return TestClient(
        create_app(
            db_url="sqlite://",
            run_executor=_InlineExecutor(),
            runs_root=tmp_path,
        )
    )


def test_hiring_contact_resource_moves_from_empty_to_ready(monkeypatch, tmp_path):
    url = "https://acme.example/team/avery"
    monkeypatch.setattr(
        contact_router, "build_hiring_contact_researcher", lambda: _Runner(url)
    )
    monkeypatch.setattr(
        contact_router,
        "build_hiring_contact_formatter",
        lambda: _Runner(
            HiringContactIntelligenceDraft(
                contacts=[
                    HiringContactDraft(
                        name="Avery Chen",
                        public_role="VP of Platform",
                        contact_type="team_leader",
                        source_urls=[url],
                    )
                ],
                generic_email_draft="Hello recruiting team",
                generic_short_message_draft="Hello team",
            )
        ),
    )
    client = _client(tmp_path)
    with client:
        with get_session(client.app.state.engine) as session:
            job = Job(source="manual", company="Acme", title="Platform Engineer")
            session.add(job)
            session.commit()
            session.refresh(job)
            assert job.id is not None
            job_id = job.id
        empty = client.get(
            f"/api/jobs/{job_id}/hiring-contact-intelligence"
        ).json()
        launched = client.post(
            f"/api/jobs/{job_id}/hiring-contact-intelligence/refreshes"
        )
        ready = client.get(
            f"/api/jobs/{job_id}/hiring-contact-intelligence"
        ).json()

    assert empty["state"] == "empty"
    assert launched.status_code == 202
    assert launched.json()["kind"] == "hiringContactIntelligence"
    assert ready["state"] == "ready"
    assert ready["intelligence"]["contacts"][0]["name"] == "Avery Chen"
    assert ready["intelligence"]["contacts"][0]["sourceUrls"] == [url]


def test_hiring_contact_openapi_has_no_send_endpoint(tmp_path):
    client = _client(tmp_path)
    with client:
        paths = client.get("/openapi.json").json()["paths"]

    resource = "/api/jobs/{job_id}/hiring-contact-intelligence"
    assert "get" in paths[resource]
    assert "post" in paths[f"{resource}/refreshes"]
    assert not any("hiring-contact" in path and "send" in path for path in paths)
