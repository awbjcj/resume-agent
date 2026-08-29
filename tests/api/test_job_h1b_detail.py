from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers.jobs import _h1b_sponsorship_response
from resume_agent.db import get_session
from resume_agent.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BPeriodStat,
    H1BSponsorshipEvidence,
)
from resume_agent.tracking.tables import H1BCompanyEvidence, Job


def _h1b_app(tmp_path):
    env = tmp_path / "h1b.env"
    env.write_text(
        "H1B_MCP_ENABLED=true\nH1B_MCP_TRANSPORT=stdio\nH1B_MCP_COMMAND=server\n",
        encoding="utf-8",
    )
    return create_app(db_url="sqlite://", env_path=env, runs_root=tmp_path)


def _evidence(*, expires_in_days: int = 30, periods=None) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    retrieved_at = now - timedelta(days=2) if expires_in_days < 0 else now
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company="acme",
        display_company="Acme",
        retrieved_at=retrieved_at,
        expires_at=now + timedelta(days=expires_in_days),
        confidence=0.9,
        caveat=HISTORICAL_ONLY_CAVEAT,
        periods=periods or [],
    )


def test_periods_and_denied_count_reach_the_wire():
    evidence = _evidence(
        periods=[
            H1BPeriodStat(
                period="FY2026-Q1", filing_count=10, certified_count=9, denied_count=1
            )
        ]
    )
    out = _h1b_sponsorship_response(evidence)
    assert out.evidence is not None
    payload = out.model_dump(by_alias=True)
    assert payload["evidence"]["periods"][0]["period"] == "FY2026-Q1"
    assert payload["evidence"]["periods"][0]["deniedCount"] == 1
    assert payload["evidence"]["deniedCount"] == 1


def test_fresh_evidence_is_not_stale():
    assert _h1b_sponsorship_response(_evidence()).stale is False


def test_expired_evidence_is_stale():
    evidence = _evidence(
        expires_in_days=-1,
        periods=[
            H1BPeriodStat(
                period="FY2026-Q1", filing_count=10, certified_count=9, denied_count=1
            )
        ],
    )
    out = _h1b_sponsorship_response(evidence)
    assert out.stale is True
    assert out.evidence is not None
    assert out.evidence.filing_count == 10
    assert out.evidence.periods[0].filing_count == 10


def test_stale_flips_exactly_at_expiry():
    evidence = _evidence(expires_in_days=1)
    assert evidence.expires_at is not None
    assert (
        _h1b_sponsorship_response(
            evidence, now=evidence.expires_at - timedelta(microseconds=1)
        ).stale
        is False
    )
    assert _h1b_sponsorship_response(evidence, now=evidence.expires_at).stale is True


def test_missing_evidence_is_not_stale():
    out = _h1b_sponsorship_response(None)
    assert out.capability == "unavailable"
    assert out.stale is False


def test_job_detail_reads_evidence_cached_by_a_sibling_job(tmp_path):
    """A job never researched itself still shows its company's cached answer."""
    app = _h1b_app(tmp_path)
    evidence = _evidence(
        periods=[H1BPeriodStat(period="FY2026-Q1", filing_count=7, certified_count=6)]
    )
    assert evidence.expires_at is not None
    assert evidence.retrieved_at is not None

    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            # Two jobs at the same company; neither carries a per-job snapshot.
            first = Job(source="manual", company="Acme, Inc.", title="A", jd_text="x")
            second = Job(source="manual", company="Acme LLC", title="B", jd_text="y")
            session.add(first)
            session.add(second)
            session.add(
                H1BCompanyEvidence(
                    normalized_company="acme",
                    display_company="Acme",
                    status="matched",
                    evidence_json=evidence.model_dump(mode="json"),
                    expires_at=evidence.expires_at,
                    retrieved_at=evidence.retrieved_at,
                )
            )
            session.commit()
            job_ids = [first.id, second.id]

        for job_id in job_ids:
            body = client.get(f"/api/jobs/{job_id}").json()
            assert body["h1BSponsorship"]["capability"] == "available"
            assert body["h1BSponsorship"]["evidence"]["filingCount"] == 7
            assert (
                body["h1BSponsorship"]["evidence"]["periods"][0]["period"]
                == "FY2026-Q1"
            )
