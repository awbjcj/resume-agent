from concurrent.futures import Executor, Future
from datetime import datetime, timedelta, timezone
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from resume_agent.api.app import create_app
from resume_agent.api.routers import jobs as jobs_router
from resume_agent.company_intelligence.models import (
    CompanyIntelligenceDraft,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_agent.db import get_session
from resume_agent.tracking.tables import CompanyIntelligenceEvidenceRow, Job


class _InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


class _DeferredExecutor(Executor):
    def __init__(self):
        self.pending = []

    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def run_next(self):
        future, fn, args, kwargs = self.pending.pop(0)
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return _Result(self.content)


def _client(tmp_path, *, executor: Executor | None = None) -> TestClient:
    return TestClient(
        create_app(
            db_url="sqlite://",
            run_executor=executor or _InlineExecutor(),
            runs_root=tmp_path,
        )
    )


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _seed(app: FastAPI, company: str | None = "Acme") -> int:
    with get_session(app.state.engine) as session:
        job = Job(source="manual", company=company, title="Engineer", jd_text="Build")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        return job.id


def _payload(now: datetime, *, expired: bool = False):
    expires_at = now - timedelta(days=1) if expired else now + timedelta(days=30)
    return {
        "normalized_company": "acme",
        "display_company": "Acme",
        "overview": "Acme builds infrastructure software.",
        "insights": [
            {
                "axis": "strategy",
                "summary": "Acme is investing in platform tooling.",
                "why_it_matters": "Ask how the team contributes.",
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
        "expires_at": expires_at.isoformat(),
        "caveat": "Verify important claims.",
    }


def _stub_company_research(monkeypatch):
    draft = CompanyIntelligenceDraft(
        overview="Acme overview",
        sources=[
            CompanyIntelligenceSource(
                title="Strategy",
                url="https://acme.example/strategy",
                publisher="Acme",
                source_type="official",
            )
        ],
        insights=[
            CompanyIntelligenceInsight(
                axis="strategy",
                summary="Acme is investing.",
                citations=["https://acme.example/strategy"],
            )
        ],
    )
    monkeypatch.setattr(
        jobs_router,
        "build_company_intelligence_researcher",
        lambda _depth="standard": _Agent("Source https://acme.example/strategy"),
    )
    monkeypatch.setattr(
        jobs_router,
        "build_company_intelligence_formatter",
        lambda: _Agent(draft),
    )


def test_job_detail_reads_stale_company_evidence_shared_by_sibling_job(tmp_path):
    client = _client(tmp_path)
    now = datetime.now(timezone.utc)
    with client:
        app = _app(client)
        first = _seed(app, "Acme, Inc.")
        second = _seed(app, "Acme LLC")
        with get_session(app.state.engine) as session:
            session.add(
                CompanyIntelligenceEvidenceRow(
                    normalized_company="acme",
                    display_company="Acme",
                    evidence_json=_payload(now, expired=True),
                    retrieved_at=now,
                    expires_at=now - timedelta(days=1),
                )
            )
            session.commit()

        for job_id in (first, second):
            body = client.get(f"/api/jobs/{job_id}").json()["companyIntelligence"]
            resource = client.get(
                f"/api/jobs/{job_id}/company-intelligence"
            ).json()
            assert body["state"] == "ready"
            assert body["canRefresh"] is True
            assert body["isStale"] is True
            assert body["capability"] == "available"
            assert body["stale"] is True
            assert body["evidence"]["insights"][0]["axis"] == "strategy"
            assert resource == body


def test_job_detail_distinguishes_empty_from_missing_company(tmp_path):
    client = _client(tmp_path)
    with client:
        empty_job = _seed(_app(client), "Acme")
        unavailable_job = _seed(_app(client), None)

        empty = client.get(f"/api/jobs/{empty_job}").json()["companyIntelligence"]
        unavailable = client.get(
            f"/api/jobs/{unavailable_job}/company-intelligence"
        ).json()

    assert empty["state"] == "empty"
    assert empty["reason"] == "not_researched"
    assert empty["canRefresh"] is True
    assert empty["evidence"] is None
    assert unavailable["state"] == "unavailable"
    assert unavailable["reason"] == "missing_company"
    assert unavailable["canRefresh"] is False


def test_explicit_refresh_launches_and_persists_grounded_dossier(monkeypatch, tmp_path):
    _stub_company_research(monkeypatch)
    client = _client(tmp_path)
    with client:
        job_id = _seed(_app(client))
        response = client.post(
            f"/api/jobs/{job_id}/company-intelligence/refreshes"
        )
        assert response.status_code == 202
        run = client.get(f"/api/runs/{response.json()['runId']}").json()
        detail = client.get(f"/api/jobs/{job_id}").json()

    assert run["state"] == "done"
    assert response.json()["kind"] == "companyIntelligence"
    assert detail["companyIntelligence"]["capability"] == "available"
    assert detail["companyIntelligence"]["evidence"]["versionNumber"] == 1


def test_refresh_depth_is_explicit_and_history_is_newest_first(monkeypatch, tmp_path):
    seen_depths = []
    _stub_company_research(monkeypatch)
    original_builder = jobs_router.build_company_intelligence_researcher

    def build_researcher(depth="standard"):
        seen_depths.append(depth)
        return original_builder(depth)

    monkeypatch.setattr(
        jobs_router,
        "build_company_intelligence_researcher",
        build_researcher,
    )
    client = _client(tmp_path)
    with client:
        job_id = _seed(_app(client))
        first = client.post(
            f"/api/jobs/{job_id}/company-intelligence/refreshes",
            json={"depth": "quick"},
        )
        second = client.post(
            f"/api/jobs/{job_id}/company-intelligence/refreshes",
            json={"depth": "deep"},
        )
        history = client.get(
            f"/api/jobs/{job_id}/company-intelligence/versions"
        ).json()

    assert first.status_code == 202
    assert second.status_code == 202
    assert seen_depths == ["quick", "deep"]
    assert [item["versionNumber"] for item in history["items"]] == [2, 1]
    assert [item["researchDepth"] for item in history["items"]] == [
        "deep",
        "quick",
    ]


def test_legacy_refresh_route_remains_accepted(monkeypatch, tmp_path):
    _stub_company_research(monkeypatch)
    client = _client(tmp_path)
    with client:
        job_id = _seed(_app(client))
        response = client.post(f"/api/jobs/{job_id}/company-intelligence")

    assert response.status_code == 202
    assert response.json()["kind"] == "companyIntelligence"


def test_refresh_keeps_company_and_singleton_identity_aligned(monkeypatch, tmp_path):
    _stub_company_research(monkeypatch)
    executor = _DeferredExecutor()
    client = _client(tmp_path, executor=executor)
    with client:
        app = _app(client)
        job_id = _seed(app, "Acme")
        response = client.post(
            f"/api/jobs/{job_id}/company-intelligence/refreshes"
        )
        with get_session(app.state.engine) as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.company = "Beta"
            session.add(job)
            session.commit()

        executor.run_next()
        acme = client.get(f"/api/jobs/{job_id}/company-intelligence").json()
        with get_session(app.state.engine) as session:
            rows = session.exec(select(CompanyIntelligenceEvidenceRow)).all()

    assert response.status_code == 202
    assert [row.normalized_company for row in rows] == ["acme"]
    assert acme["state"] == "empty"


def test_explicit_refresh_requires_company(tmp_path):
    client = _client(tmp_path)
    with client:
        job_id = _seed(_app(client), company=None)
        response = client.post(
            f"/api/jobs/{job_id}/company-intelligence/refreshes"
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_openapi_exposes_resource_routes_and_hides_legacy_refresh_alias(tmp_path):
    client = _client(tmp_path)
    with client:
        paths = client.get("/openapi.json").json()["paths"]

    resource_path = "/api/jobs/{job_id}/company-intelligence"
    refresh_path = f"{resource_path}/refreshes"
    versions_path = f"{resource_path}/versions"
    assert "get" in paths[resource_path]
    assert "post" not in paths[resource_path]
    assert "post" in paths[refresh_path]
    assert "get" in paths[versions_path]
