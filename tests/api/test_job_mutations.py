from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.api.routers import jobs as jobs_router
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

    async def fake_check(session, job, *, settings):
        assert job.company == "Acme"
        assert settings.h1b_mcp_enabled is True
        return evidence

    monkeypatch.setattr(jobs_router, "check_job_sponsorship", fake_check)
    env = tmp_path / "h1b.env"
    env.write_text(
        "H1B_MCP_ENABLED=true\n"
        "H1B_MCP_TRANSPORT=stdio\n"
        "H1B_MCP_COMMAND=server\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(db_url="sqlite://", env_path=env))
    with client:
        jid = _seed(client.app, company="Acme")
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")

    assert response.status_code == 200
    assert response.json()["capability"] == "available"
    assert response.json()["evidence"]["status"] == "matched"


def test_manual_h1b_check_reports_disabled():
    client = _client()
    with client:
        jid = _seed(client.app, company="Acme")
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")

    assert response.status_code == 200
    assert response.json() == {"capability": "disabled", "evidence": None}


def test_manual_h1b_check_requires_a_company(tmp_path):
    env = tmp_path / "h1b.env"
    env.write_text(
        "H1B_MCP_ENABLED=true\n"
        "H1B_MCP_TRANSPORT=stdio\n"
        "H1B_MCP_COMMAND=server\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(db_url="sqlite://", env_path=env))
    with client:
        jid = _seed(client.app)
        response = client.post(f"/api/jobs/{jid}/h1b-sponsorship")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


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
