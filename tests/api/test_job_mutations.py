from concurrent.futures import Executor, Future
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.h1b import service as h1b_service
from resume_agent.h1b.models import (
    H1B_AGENT_UNAVAILABLE_REASON,
    HISTORICAL_ONLY_CAVEAT,
    H1BEnrichmentReport,
    H1BSponsorshipEvidence,
)
from resume_agent.tracking.tables import H1BCompanyEvidence, Job, JobStatus


class InlineExecutor(Executor):
    """Runs submitted callables immediately, in-thread — deterministic for tests."""

    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _h1b_client(tmp_path, *, enabled=True):
    env = tmp_path / "h1b.env"
    env.write_text(
        (
            "H1B_MCP_ENABLED=true\n"
            "H1B_MCP_TRANSPORT=stdio\n"
            "H1B_MCP_COMMAND=server\n"
            if enabled
            else ""
        ),
        encoding="utf-8",
    )
    return TestClient(
        create_app(
            db_url="sqlite://",
            env_path=env,
            run_executor=InlineExecutor(),
            runs_root=tmp_path,
        )
    )


def _seed(app, **kw):
    with get_session(app.state.engine) as s:
        source = kw.pop("source", "manual")
        job = Job(source=source, jd_text="x", **kw)
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def _persist_h1b_cache(engine, report: H1BEnrichmentReport) -> None:
    """Mirror enrich_companies' durable company-cache write in mocked runs."""
    with get_session(engine) as session:
        for normalized, evidence in report.by_company.items():
            session.add(
                H1BCompanyEvidence(
                    normalized_company=normalized,
                    display_company=evidence.display_company,
                    status=evidence.status,
                    evidence_json=evidence.model_dump(mode="json"),
                    source_url=evidence.source_url,
                    data_version=evidence.data_version,
                    retrieved_at=evidence.retrieved_at,
                    expires_at=evidence.expires_at,
                )
            )
        session.commit()


def test_patch_status_approves():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.shortlisted.value)
        resp = client.patch(f"/api/jobs/{jid}", json={"status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_manual_h1b_check_returns_evidence(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    evidence = H1BSponsorshipEvidence(
        status="matched",
        normalized_company="acme",
        display_company="Acme",
        fiscal_periods=["2024"],
        filing_count=2,
        certified_count=1,
        wage_summary={"median": 150000.0},
        source_url="https://example.com/data",
        data_version="fixture-v1",
        retrieved_at=now,
        expires_at=now + timedelta(days=1),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )

    async def fake_enrich(engine, companies, *, settings, agent_factory, company_resolver_factory=None, force_refresh=False):
        assert settings.h1b_mcp_enabled is True
        report = H1BEnrichmentReport(by_company={"acme": evidence})
        _persist_h1b_cache(engine, report)
        return report

    monkeypatch.setattr(h1b_service, "enrich_companies", fake_enrich)
    client = _h1b_client(tmp_path)
    with client:
        jid = _seed(client.app, company="Acme")
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")
        assert response.status_code == 202
        run = client.get(f"/api/runs/{response.json()['runId']}").json()
        assert run["state"] == "done"
        detail = client.get(f"/api/jobs/{jid}").json()

    assert detail["h1BSponsorship"]["capability"] == "available"
    assert detail["h1BSponsorship"]["evidence"]["status"] == "matched"


def test_manual_h1b_check_reports_disabled():
    client = _client()
    with client:
        jid = _seed(client.app, company="Acme")
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "H1B_DISABLED"


def test_manual_h1b_check_requires_a_company(tmp_path):
    client = _h1b_client(tmp_path)
    with client:
        jid = _seed(client.app)
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_manual_h1b_check_reports_unavailable_evidence(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    evidence = H1BSponsorshipEvidence(
        status="unavailable",
        normalized_company="acme",
        display_company="Acme",
        retrieved_at=now,
        expires_at=now + timedelta(minutes=5),
        confidence=0.0,
        caveat=HISTORICAL_ONLY_CAVEAT,
        unavailable_reason=H1B_AGENT_UNAVAILABLE_REASON,
    )

    async def fake_enrich(engine, companies, *, settings, agent_factory, company_resolver_factory=None, force_refresh=False):
        report = H1BEnrichmentReport(by_company={"acme": evidence})
        _persist_h1b_cache(engine, report)
        return report

    monkeypatch.setattr(h1b_service, "enrich_companies", fake_enrich)
    client = _h1b_client(tmp_path)
    with client:
        jid = _seed(client.app, company="Acme")
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")
        assert response.status_code == 202
        run = client.get(f"/api/runs/{response.json()['runId']}").json()
        assert run["state"] == "done"
        detail = client.get(f"/api/jobs/{jid}").json()

    assert detail["h1BSponsorship"]["capability"] == "unavailable"
    assert detail["h1BSponsorship"]["message"] == H1B_AGENT_UNAVAILABLE_REASON
    assert detail["h1BSponsorship"]["evidence"]["unavailableReason"] == H1B_AGENT_UNAVAILABLE_REASON


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


def test_bulk_delete_query_dry_run_uses_board_filter():
    client = _client()
    with client:
        _seed(client.app, status=JobStatus.raw.value, source="adzuna")
        _seed(client.app, status=JobStatus.raw.value, source="manual")
        resp = client.post(
            "/api/jobs/bulk",
            json={
                "board": "triage",
                "action": "delete",
                "scope": "query",
                "source": ["adzuna"],
                "dryRun": True,
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {"affected": 1, "skipped": 0, "reasons": {}}


def test_bulk_query_rejects_unknown_sort_and_preset_values():
    client = _client()
    with client:
        base = {
            "board": "pipeline",
            "action": "archive",
            "scope": "query",
            "dryRun": True,
        }
        bad_sort = client.post(
            "/api/jobs/bulk",
            json={**base, "sortBy": "not-a-sort"},
        )
        bad_preset = client.post(
            "/api/jobs/bulk",
            json={**base, "preset": "not-a-preset"},
        )

    assert bad_sort.status_code == 422
    assert bad_preset.status_code == 422
