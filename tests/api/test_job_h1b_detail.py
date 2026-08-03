from datetime import datetime, timedelta, timezone

from resume_agent.api.routers.jobs import _h1b_sponsorship_response
from resume_agent.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BPeriodStat,
    H1BSponsorshipEvidence,
)


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
    assert _h1b_sponsorship_response(
        evidence, now=evidence.expires_at - timedelta(microseconds=1)
    ).stale is False
    assert _h1b_sponsorship_response(evidence, now=evidence.expires_at).stale is True


def test_missing_evidence_is_not_stale():
    out = _h1b_sponsorship_response(None)
    assert out.capability == "unavailable"
    assert out.stale is False
