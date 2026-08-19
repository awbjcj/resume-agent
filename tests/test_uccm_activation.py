from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


EXPECTED = {
    "taxonomy_revision": "taxonomy-v1",
    "assertion_policy_revision": "profile-assertions-v1",
    "extraction_policy_revision": "job-requirements-v1",
    "matching_policy_revision": "uccm-match-v1",
}


def _passing_report(**updates):
    from resume_agent.matching.activation import (
        REQUIRED_CAREER_FAMILIES,
        REQUIRED_CAREER_LEVELS,
        UccmActivationReport,
        seal_activation_report,
    )

    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    data = {
        "report_revision": "release-report-v1",
        "evaluation_revision": "uccm-eval-v1",
        "gold_set_revision": "gold-v1",
        "reviewed": True,
        "reviewer_ids": ["evaluation-owner"],
        "generated_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(days=30),
        **EXPECTED,
        "reviewed_record_count": 240,
        "career_families": sorted(REQUIRED_CAREER_FAMILIES),
        "career_levels": sorted(REQUIRED_CAREER_LEVELS),
        "metrics": {
            "exact_synonym_precision": 0.99,
            "strict_false_positive_rate": 0.0,
            "resume_claim_precision": 1.0,
            "transfer_precision": 0.95,
            "transfer_must_have_credit_precision": 0.98,
            "adversarial_false_transfer_rate": 0.01,
            "concept_type_macro_f1": 0.95,
            "match_status_macro_f1": 0.9,
            "match_status_min_f1": 0.82,
            "correction_propagation_rate": 1.0,
            "deterministic_reproduction_rate": 1.0,
        },
        "failed_gates": [],
        "eligible": True,
    }
    data.update(updates)
    report = UccmActivationReport.model_validate(data)
    return seal_activation_report(report)


def _decide(report):
    from resume_agent.matching.activation import decide_uccm_activation

    return decide_uccm_activation(
        "uccm",
        report,
        now=datetime(2026, 8, 19, tzinfo=timezone.utc),
        **EXPECTED,
    )


def test_legacy_and_shadow_modes_never_require_a_release_report():
    from resume_agent.matching.activation import decide_uccm_activation

    for mode in ("legacy", "shadow"):
        decision = decide_uccm_activation(
            mode,
            None,
            now=datetime(2026, 8, 19, tzinfo=timezone.utc),
            **EXPECTED,
        )
        assert decision.effective_mode == mode
        assert decision.reason_code == "activation_not_required"


@pytest.mark.parametrize(
    ("report", "reason"),
    [
        (None, "activation_report_missing"),
        (_passing_report(reviewed=False), "activation_report_unreviewed"),
        (_passing_report(reviewer_ids=[]), "activation_report_unreviewed"),
        (_passing_report(expires_at=datetime(2026, 8, 18, tzinfo=timezone.utc)), "activation_report_stale"),
        (_passing_report(taxonomy_revision="other"), "activation_report_revision_mismatch"),
        (_passing_report(eligible=False), "activation_report_ineligible"),
        (_passing_report(failed_gates=["transfer_precision"]), "activation_report_ineligible"),
    ],
)
def test_uccm_falls_back_to_shadow_for_ineligible_reports(report, reason):
    decision = _decide(report)

    assert decision.requested_mode == "uccm"
    assert decision.effective_mode == "shadow"
    assert decision.eligible is False
    assert decision.reason_code == reason


def test_uccm_rejects_unsigned_and_tampered_reports():
    unsigned = _passing_report().model_copy(update={"approval_signature": ""})
    assert _decide(unsigned).reason_code == "activation_report_unsigned"

    tampered = _passing_report().model_copy(update={"reviewed_record_count": 241})
    assert _decide(tampered).reason_code == "activation_report_checksum_mismatch"


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("exact_synonym_precision", 0.979),
        ("strict_false_positive_rate", 0.006),
        ("resume_claim_precision", 0.994),
        ("transfer_precision", 0.919),
        ("transfer_must_have_credit_precision", 0.969),
        ("adversarial_false_transfer_rate", 0.031),
        ("concept_type_macro_f1", 0.929),
        ("match_status_macro_f1", 0.879),
        ("match_status_min_f1", 0.799),
        ("correction_propagation_rate", 0.999),
        ("deterministic_reproduction_rate", 0.999),
    ],
)
def test_every_published_threshold_is_fail_closed(metric, value):
    report = _passing_report()
    metrics = report.metrics.model_copy(update={metric: value})
    report = seal_again(report.model_copy(update={"metrics": metrics}))

    decision = _decide(report)

    assert decision.effective_mode == "shadow"
    assert decision.reason_code == "activation_report_threshold_failed"
    assert decision.checked_thresholds[metric] is False


def seal_again(report):
    from resume_agent.matching.activation import seal_activation_report

    return seal_activation_report(
        report.model_copy(update={"checksum": "", "approval_signature": ""})
    )


def test_missing_metric_denominator_and_coverage_are_fail_closed():
    report = _passing_report()
    missing_metric = seal_again(
        report.model_copy(
            update={
                "metrics": report.metrics.model_copy(
                    update={"transfer_precision": None}
                )
            }
        )
    )
    missing_coverage = seal_again(report.model_copy(update={"career_families": []}))

    assert _decide(missing_metric).reason_code == "activation_report_incomplete"
    assert _decide(missing_coverage).reason_code == "activation_report_incomplete"


def test_complete_reviewed_report_activates_uccm_primary():
    decision = _decide(_passing_report())

    assert decision.effective_mode == "uccm"
    assert decision.eligible is True
    assert decision.reason_code == "activation_eligible"
    assert all(decision.checked_thresholds.values())
    assert decision.report_revision == "release-report-v1"
