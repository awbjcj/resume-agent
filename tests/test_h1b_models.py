from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from resume_agent.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BPeriodStat,
    H1BSponsorshipEvidence,
)


def _evidence(**overrides) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    payload = {
        "status": "matched",
        "normalized_company": "acme",
        "retrieved_at": now,
        "expires_at": now + timedelta(days=30),
        "confidence": 0.8,
        "caveat": HISTORICAL_ONLY_CAVEAT,
    }
    payload.update(overrides)
    return H1BSponsorshipEvidence(**payload)


def test_rollup_overwrites_totals_that_disagree_with_their_parts():
    evidence = _evidence(
        filing_count=999,
        certified_count=999,
        denied_count=999,
        periods=[
            H1BPeriodStat(period="FY2026-Q1", filing_count=10, certified_count=9, denied_count=1),
            H1BPeriodStat(period="FY2025-Q4", filing_count=4, certified_count=3, denied_count=1),
        ],
    )
    assert evidence.filing_count == 14
    assert evidence.certified_count == 12
    assert evidence.denied_count == 2


def test_metric_no_period_reports_rolls_up_to_none_not_zero():
    evidence = _evidence(
        periods=[
            H1BPeriodStat(period="FY2026-Q1", filing_count=10),
            H1BPeriodStat(period="FY2025-Q4", filing_count=4),
        ],
    )
    assert evidence.filing_count == 14
    assert evidence.certified_count is None
    assert evidence.denied_count is None


def test_partially_reported_metric_sums_only_present_values():
    evidence = _evidence(
        periods=[
            H1BPeriodStat(period="FY2026-Q1", certified_count=9),
            H1BPeriodStat(period="FY2025-Q4"),
        ],
    )
    assert evidence.certified_count == 9


def test_duplicate_period_labels_reject():
    with pytest.raises(ValidationError):
        _evidence(
            periods=[
                H1BPeriodStat(period="FY2026-Q1", filing_count=1),
                H1BPeriodStat(period="FY2026-Q1", filing_count=2),
            ],
        )


def test_more_than_four_periods_reject():
    with pytest.raises(ValidationError):
        _evidence(
            periods=[H1BPeriodStat(period=f"FY-Q{i}", filing_count=1) for i in range(5)],
        )


def test_legacy_payload_without_periods_still_validates():
    evidence = _evidence(filing_count=12, certified_count=8)
    assert evidence.periods == []
    assert evidence.denied_count is None
    assert evidence.filing_count == 12


def test_period_rejects_outcomes_exceeding_filings():
    with pytest.raises(ValidationError):
        H1BPeriodStat(
            period="FY2026-Q1", filing_count=5, certified_count=4, denied_count=3
        )


def test_denied_count_cannot_exceed_filing_count_without_periods():
    with pytest.raises(ValidationError):
        _evidence(filing_count=2, denied_count=3)


def test_legacy_total_rejects_combined_outcomes_over_filings():
    with pytest.raises(ValidationError):
        _evidence(filing_count=2, certified_count=1, denied_count=2)
