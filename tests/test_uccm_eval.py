from __future__ import annotations

from itertools import product
from datetime import datetime, timedelta, timezone
from typing import Literal


FAMILIES = [
    "software_data",
    "engineering_manufacturing",
    "finance_accounting",
    "human_resources",
    "education_research",
    "consulting_operations",
    "creative_media",
    "sales_customer",
    "healthcare_social_services",
    "legal_policy",
    "logistics_skilled_operations",
    "public_nonprofit_administration",
]
LEVELS: list[Literal["entry", "mid", "senior", "manager"]] = [
    "entry",
    "mid",
    "senior",
    "manager",
]


def _perfect_records():
    from evals.uccm import UccmEvalRecord

    return [
        UccmEvalRecord(
            id=f"{family}:{level}",
            career_family=family,
            career_level=level,
            review_status="reviewed",
            concept_type_gold="capability",
            concept_type_predicted="capability",
            match_status_gold="verified_exact",
            match_status_predicted="verified_exact",
            exact_or_synonym_gold_positive=True,
            exact_or_synonym_predicted_positive=True,
            strict_requirement=True,
            strict_false_positive=False,
            resume_claim_predicted=True,
            resume_claim_supported=True,
            transfer_predicted=True,
            transfer_correct=True,
            must_have_positive_credit=True,
            adversarial_same_domain_negative=True,
            false_transfer=False,
            correction_propagated=True,
            reproduced=True,
        )
        for family, level in product(FAMILIES, LEVELS)
    ]


def test_complete_perfect_reviewed_set_passes_every_release_gate():
    from evals.uccm import GoldSetManifest, evaluate_uccm

    report = evaluate_uccm(
        _perfect_records(),
        GoldSetManifest(
            revision="gold-v1",
            reviewed=True,
            reviewer_ids=["reviewer:1"],
        ),
    )

    assert report.eligible is True
    assert report.failed_gates == []
    assert report.metrics.exact_synonym_precision == 1.0
    assert report.metrics.strict_false_positive_rate == 0.0
    assert report.metrics.concept_type_macro_f1 == 1.0
    assert report.metrics.match_status_macro_f1 == 1.0
    assert report.checksum


def test_missing_review_coverage_or_denominator_fails_closed():
    from evals.uccm import GoldSetManifest, UccmEvalRecord, evaluate_uccm

    report = evaluate_uccm(
        [
            UccmEvalRecord(
                id="one",
                career_family=FAMILIES[0],
                career_level="entry",
                review_status="unreviewed",
            )
        ],
        GoldSetManifest(revision="draft", reviewed=False),
    )

    assert report.eligible is False
    assert "gold_set_not_reviewed" in report.failed_gates
    assert "insufficient_career_coverage" in report.failed_gates
    assert "exact_synonym_precision_missing" in report.failed_gates


def test_one_strict_false_positive_fails_the_threshold():
    from evals.uccm import GoldSetManifest, evaluate_uccm

    records = _perfect_records()
    records[0] = records[0].model_copy(update={"strict_false_positive": True})
    report = evaluate_uccm(
        records,
        GoldSetManifest(
            revision="gold-v1",
            reviewed=True,
            reviewer_ids=["reviewer:1"],
        ),
    )

    assert report.eligible is False
    assert "strict_false_positive_rate" in report.failed_gates


def test_report_is_deterministic_under_record_reordering():
    from evals.uccm import GoldSetManifest, evaluate_uccm

    manifest = GoldSetManifest(
        revision="gold-v1",
        reviewed=True,
        reviewer_ids=["reviewer:1"],
    )
    records = _perfect_records()

    assert evaluate_uccm(records, manifest).checksum == evaluate_uccm(
        list(reversed(records)), manifest
    ).checksum


def test_reviewed_eval_can_be_sealed_as_the_runtime_activation_report():
    from evals.uccm import GoldSetManifest, build_activation_report, evaluate_uccm
    from resume_agent.matching.activation import decide_uccm_activation

    manifest = GoldSetManifest(
        revision="gold-v1", reviewed=True, reviewer_ids=["reviewer:1"]
    )
    evaluated = evaluate_uccm(_perfect_records(), manifest)
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    report = build_activation_report(
        evaluated,
        manifest,
        report_revision="release-v1",
        taxonomy_revision="taxonomy-v1",
        assertion_policy_revision="profile-assertions-v1",
        extraction_policy_revision="job-requirements-v1",
        matching_policy_revision="uccm-match-v1",
        generated_at=now,
        expires_at=now + timedelta(days=30),
    )

    decision = decide_uccm_activation(
        "uccm",
        report,
        now=now,
        taxonomy_revision="taxonomy-v1",
        assertion_policy_revision="profile-assertions-v1",
        extraction_policy_revision="job-requirements-v1",
        matching_policy_revision="uccm-match-v1",
    )
    assert decision.effective_mode == "uccm"
    assert report.checksum
    assert report.approval_signature
