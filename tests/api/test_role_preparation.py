from concurrent.futures import Executor, Future
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import role_preparation as role_router
from resume_agent.db import get_session
from resume_agent.role_preparation.models import (
    RolePreparationAsk,
    RolePreparationDraft,
    RolePreparationQuestion,
)
from resume_agent.tracking.tables import CompanyIntelligenceEvidenceRow, Job


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


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _seed(app: FastAPI, *, with_evidence: bool = True) -> int:
    now = datetime.now(timezone.utc)
    with get_session(app.state.engine) as session:
        job = Job(
            source="manual",
            company="Acme",
            title="Platform Engineer",
            jd_text="Own platform services",
        )
        session.add(job)
        if with_evidence:
            session.add(
                CompanyIntelligenceEvidenceRow(
                    normalized_company="acme",
                    display_company="Acme",
                    evidence_json={
                        "normalized_company": "acme",
                        "display_company": "Acme",
                        "overview": "Acme builds infrastructure.",
                        "insights": [
                            {
                                "axis": "strategy",
                                "summary": "Acme invests in platform tooling.",
                                "citations": ["https://acme.example/strategy"],
                            }
                        ],
                        "sources": [
                            {
                                "title": "Strategy",
                                "url": "https://acme.example/strategy",
                                "publisher": "Acme",
                                "source_type": "official",
                            }
                        ],
                        "retrieved_at": now.isoformat(),
                        "expires_at": (now + timedelta(days=30)).isoformat(),
                        "caveat": "Verify",
                        "version_id": 7,
                        "version_number": 2,
                    },
                    retrieved_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
        session.commit()
        session.refresh(job)
        assert job.id is not None
        return job.id


def _draft():
    return RolePreparationDraft(
        positioning_summary="Lead with platform ownership.",
        likely_questions=[
            RolePreparationQuestion(
                question="How have you owned a production platform?",
                question_type="behavioral",
                company_citations=["https://acme.example/strategy"],
            )
        ],
        questions_to_ask=[
            RolePreparationAsk(
                text="How does this team contribute to the platform strategy?",
                company_citations=["https://acme.example/strategy"],
            )
        ],
    )


def test_role_preparation_resource_moves_from_empty_to_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(
        role_router,
        "build_role_preparation_formatter",
        lambda: _Runner(_draft()),
    )
    client = _client(tmp_path)
    with client:
        app = _app(client)
        job_id = _seed(app)
        empty = client.get(f"/api/jobs/{job_id}/role-preparation-brief").json()
        launched = client.post(
            f"/api/jobs/{job_id}/role-preparation-brief/refreshes"
        )
        ready = client.get(f"/api/jobs/{job_id}/role-preparation-brief").json()
        with get_session(app.state.engine) as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.jd_text = "Changed role scope"
            session.add(job)
            session.commit()
        changed = client.get(f"/api/jobs/{job_id}/role-preparation-brief").json()

    assert empty["state"] == "empty"
    assert empty["canRefresh"] is True
    assert launched.status_code == 202
    assert launched.json()["kind"] == "rolePreparation"
    assert ready["state"] == "ready"
    assert ready["inputsChanged"] is False
    assert ready["brief"]["companyIntelligenceVersionId"] == 7
    assert ready["brief"]["likelyQuestions"][0]["questionType"] == "behavioral"
    assert changed["inputsChanged"] is True


def test_role_preparation_requires_saved_company_intelligence(tmp_path):
    client = _client(tmp_path)
    with client:
        job_id = _seed(_app(client), with_evidence=False)
        resource = client.get(f"/api/jobs/{job_id}/role-preparation-brief").json()
        response = client.post(
            f"/api/jobs/{job_id}/role-preparation-brief/refreshes"
        )

    assert resource["state"] == "unavailable"
    assert resource["reason"] == "company_intelligence_required"
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROLE_PREPARATION_UNAVAILABLE"


def test_openapi_exposes_role_preparation_resource_and_refresh(tmp_path):
    client = _client(tmp_path)
    with client:
        paths = client.get("/openapi.json").json()["paths"]

    resource = "/api/jobs/{job_id}/role-preparation-brief"
    assert "get" in paths[resource]
    assert "post" in paths[f"{resource}/refreshes"]
