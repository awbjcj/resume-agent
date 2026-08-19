"""Fail-closed release policy for making UCCM results primary."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.graph_models import CareerCapabilityMode

REQUIRED_CAREER_FAMILIES = frozenset(
    {
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
    }
)
REQUIRED_CAREER_LEVELS = frozenset({"entry", "mid", "senior", "manager"})


class UccmActivationMetrics(ExtensibleModel):
    exact_synonym_precision: float | None = None
    strict_false_positive_rate: float | None = None
    resume_claim_precision: float | None = None
    transfer_precision: float | None = None
    transfer_must_have_credit_precision: float | None = None
    adversarial_false_transfer_rate: float | None = None
    concept_type_macro_f1: float | None = None
    match_status_macro_f1: float | None = None
    match_status_min_f1: float | None = None
    correction_propagation_rate: float | None = None
    deterministic_reproduction_rate: float | None = None


class UccmActivationReport(ExtensibleModel):
    report_revision: str
    evaluation_revision: str
    gold_set_revision: str
    reviewed: bool = False
    reviewer_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    expires_at: datetime
    taxonomy_revision: str
    assertion_policy_revision: str
    extraction_policy_revision: str
    matching_policy_revision: str
    reviewed_record_count: int = Field(ge=0)
    career_families: list[str] = Field(default_factory=list)
    career_levels: list[str] = Field(default_factory=list)
    metrics: UccmActivationMetrics
    failed_gates: list[str] = Field(default_factory=list)
    eligible: bool = False
    checksum: str = ""
    approval_signature: str = ""


class UccmActivationDecision(ExtensibleModel):
    requested_mode: CareerCapabilityMode
    effective_mode: CareerCapabilityMode
    eligible: bool
    reason_code: str
    report_revision: str | None = None
    taxonomy_revision: str
    assertion_policy_revision: str
    extraction_policy_revision: str
    matching_policy_revision: str
    checked_thresholds: dict[str, bool] = Field(default_factory=dict)


_MINIMUMS = {
    "exact_synonym_precision": 0.98,
    "resume_claim_precision": 0.995,
    "transfer_precision": 0.92,
    "transfer_must_have_credit_precision": 0.97,
    "concept_type_macro_f1": 0.93,
    "match_status_macro_f1": 0.88,
    "match_status_min_f1": 0.80,
    "correction_propagation_rate": 1.0,
    "deterministic_reproduction_rate": 1.0,
}
_MAXIMUMS = {
    "strict_false_positive_rate": 0.005,
    "adversarial_false_transfer_rate": 0.03,
}


def _checksum(report: UccmActivationReport) -> str:
    payload = report.model_dump(
        mode="json", exclude={"checksum", "approval_signature"}
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _approval_signature(checksum: str, reviewer_ids: list[str]) -> str:
    attestation = f"uccm-reviewed:{checksum}:{','.join(sorted(reviewer_ids))}"
    return hashlib.sha256(attestation.encode()).hexdigest()


def seal_activation_report(report: UccmActivationReport) -> UccmActivationReport:
    """Create the deterministic reviewed-report seal used by offline tooling."""
    checksum = _checksum(report)
    return report.model_copy(
        update={
            "checksum": checksum,
            "approval_signature": _approval_signature(
                checksum, report.reviewer_ids
            ),
        }
    )


def _thresholds(metrics: UccmActivationMetrics) -> dict[str, bool]:
    values = metrics.model_dump()
    checked = {
        name: values[name] is not None and values[name] >= threshold
        for name, threshold in _MINIMUMS.items()
    }
    checked.update(
        {
            name: values[name] is not None and values[name] <= threshold
            for name, threshold in _MAXIMUMS.items()
        }
    )
    return dict(sorted(checked.items()))


def _decision(
    requested_mode: CareerCapabilityMode,
    effective_mode: CareerCapabilityMode,
    *,
    eligible: bool,
    reason_code: str,
    report: UccmActivationReport | None,
    taxonomy_revision: str,
    assertion_policy_revision: str,
    extraction_policy_revision: str,
    matching_policy_revision: str,
    checked_thresholds: dict[str, bool] | None = None,
) -> UccmActivationDecision:
    return UccmActivationDecision(
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        eligible=eligible,
        reason_code=reason_code,
        report_revision=report.report_revision if report is not None else None,
        taxonomy_revision=taxonomy_revision,
        assertion_policy_revision=assertion_policy_revision,
        extraction_policy_revision=extraction_policy_revision,
        matching_policy_revision=matching_policy_revision,
        checked_thresholds=checked_thresholds or {},
    )


def decide_uccm_activation(
    requested_mode: CareerCapabilityMode,
    report: UccmActivationReport | None,
    *,
    now: datetime | None = None,
    taxonomy_revision: str,
    assertion_policy_revision: str,
    extraction_policy_revision: str,
    matching_policy_revision: str,
) -> UccmActivationDecision:
    """Resolve one deployment mode without mutating artifacts or configuration."""
    if requested_mode != "uccm":
        return _decision(
            requested_mode,
            requested_mode,
            eligible=True,
            reason_code="activation_not_required",
            report=report,
            taxonomy_revision=taxonomy_revision,
            assertion_policy_revision=assertion_policy_revision,
            extraction_policy_revision=extraction_policy_revision,
            matching_policy_revision=matching_policy_revision,
        )
    if report is None:
        return _decision(
            requested_mode,
            "shadow",
            eligible=False,
            reason_code="activation_report_missing",
            report=None,
            taxonomy_revision=taxonomy_revision,
            assertion_policy_revision=assertion_policy_revision,
            extraction_policy_revision=extraction_policy_revision,
            matching_policy_revision=matching_policy_revision,
        )
    checked = _thresholds(report.metrics)
    def fallback(reason_code: str) -> UccmActivationDecision:
        return _decision(
            requested_mode,
            "shadow",
            eligible=False,
            reason_code=reason_code,
            report=report,
            checked_thresholds=checked,
            taxonomy_revision=taxonomy_revision,
            assertion_policy_revision=assertion_policy_revision,
            extraction_policy_revision=extraction_policy_revision,
            matching_policy_revision=matching_policy_revision,
        )

    if not report.reviewed or not report.reviewer_ids:
        return fallback("activation_report_unreviewed")
    if not report.approval_signature:
        return fallback("activation_report_unsigned")
    expected_checksum = _checksum(report)
    expected_signature = _approval_signature(expected_checksum, report.reviewer_ids)
    if report.checksum != expected_checksum or report.approval_signature != expected_signature:
        return fallback("activation_report_checksum_mismatch")
    now = now or datetime.now(timezone.utc)
    if report.expires_at <= now or report.generated_at > now:
        return fallback("activation_report_stale")
    expected_revisions = (
        taxonomy_revision,
        assertion_policy_revision,
        extraction_policy_revision,
        matching_policy_revision,
    )
    report_revisions = (
        report.taxonomy_revision,
        report.assertion_policy_revision,
        report.extraction_policy_revision,
        report.matching_policy_revision,
    )
    if report_revisions != expected_revisions:
        return fallback("activation_report_revision_mismatch")
    complete = (
        report.reviewed_record_count > 0
        and REQUIRED_CAREER_FAMILIES.issubset(report.career_families)
        and REQUIRED_CAREER_LEVELS.issubset(report.career_levels)
        and all(value is not None for value in report.metrics.model_dump().values())
    )
    if not complete:
        return fallback("activation_report_incomplete")
    if not report.eligible or report.failed_gates:
        return fallback("activation_report_ineligible")
    if not all(checked.values()):
        return fallback("activation_report_threshold_failed")
    return _decision(
        requested_mode,
        "uccm",
        eligible=True,
        reason_code="activation_eligible",
        report=report,
        checked_thresholds=checked,
        taxonomy_revision=taxonomy_revision,
        assertion_policy_revision=assertion_policy_revision,
        extraction_policy_revision=extraction_policy_revision,
        matching_policy_revision=matching_policy_revision,
    )


def load_activation_report(path: str | Path) -> UccmActivationReport | None:
    try:
        return UccmActivationReport.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
