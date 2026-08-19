"""Offline UCCM gold-set metrics and fail-closed release gates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.matching.models import MatchStatus
from resume_agent.matching.activation import (
    MINIMUM_GATE_DENOMINATORS,
    MINIMUM_RECORDS_PER_STRATUM,
    REQUIRED_CAREER_FAMILIES,
    REQUIRED_CAREER_LEVELS,
    REQUIRED_CONCEPT_TYPES,
    REQUIRED_MATCH_STATUSES,
    UccmActivationMetrics,
    UccmActivationReport,
    seal_activation_report,
)
from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.term_typing import TermConceptType

class GoldSetManifest(ExtensibleModel):
    revision: str
    reviewed: bool = False
    reviewer_ids: list[str] = Field(default_factory=list)


class UccmEvalRecord(ExtensibleModel):
    id: str
    career_family: str
    career_level: Literal["entry", "mid", "senior", "manager"]
    review_status: Literal["unreviewed", "reviewed", "disputed"] = "unreviewed"
    concept_type_gold: TermConceptType | None = None
    concept_type_predicted: TermConceptType | None = None
    match_status_gold: MatchStatus | None = None
    match_status_predicted: MatchStatus | None = None
    exact_or_synonym_gold_positive: bool | None = None
    exact_or_synonym_predicted_positive: bool | None = None
    strict_requirement: bool = False
    strict_false_positive: bool = False
    resume_claim_predicted: bool = False
    resume_claim_supported: bool = False
    transfer_predicted: bool = False
    transfer_correct: bool = False
    must_have_positive_credit: bool = False
    adversarial_same_domain_negative: bool = False
    false_transfer: bool = False
    correction_propagated: bool | None = None
    reproduced: bool | None = None


class UccmMetrics(ExtensibleModel):
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


class UccmEvaluationReport(ExtensibleModel):
    evaluation_revision: str = "uccm-eval-v1"
    gold_set_revision: str
    reviewed_record_count: int
    metrics: UccmMetrics
    career_families: list[str] = Field(default_factory=list)
    career_levels: list[str] = Field(default_factory=list)
    stratum_counts: dict[str, int] = Field(default_factory=dict)
    concept_types: list[str] = Field(default_factory=list)
    match_statuses: list[str] = Field(default_factory=list)
    metric_denominators: dict[str, int] = Field(default_factory=dict)
    failed_gates: list[str] = Field(default_factory=list)
    eligible: bool = False
    checksum: str


def _precision(records: list[tuple[bool, bool]]) -> float | None:
    predicted = [gold for gold, prediction in records if prediction]
    if not predicted:
        return None
    return sum(predicted) / len(predicted)


def _rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _predicted_count(records: list[tuple[bool, bool]]) -> int:
    return sum(prediction for _, prediction in records)


def _macro_f1(pairs: list[tuple[str, str]]) -> tuple[float, float] | None:
    if not pairs:
        return None
    labels = sorted({label for pair in pairs for label in pair})
    scores: list[float] = []
    for label in labels:
        true_positive = sum(gold == predicted == label for gold, predicted in pairs)
        false_positive = sum(
            predicted == label and gold != label for gold, predicted in pairs
        )
        false_negative = sum(
            gold == label and predicted != label for gold, predicted in pairs
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return sum(scores) / len(scores), min(scores)


def _threshold(
    failed: list[str],
    *,
    name: str,
    value: float | None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if value is None:
        failed.append(f"{name}_missing")
    elif minimum is not None and value < minimum:
        failed.append(name)
    elif maximum is not None and value > maximum:
        failed.append(name)


def evaluate_uccm(
    records: list[UccmEvalRecord],
    manifest: GoldSetManifest,
) -> UccmEvaluationReport:
    reviewed = sorted(
        (record for record in records if record.review_status == "reviewed"),
        key=lambda item: item.id,
    )
    type_pairs = [
        (record.concept_type_gold, record.concept_type_predicted)
        for record in reviewed
        if record.concept_type_gold is not None
        and record.concept_type_predicted is not None
    ]
    status_pairs = [
        (record.match_status_gold, record.match_status_predicted)
        for record in reviewed
        if record.match_status_gold is not None
        and record.match_status_predicted is not None
    ]
    type_f1 = _macro_f1(type_pairs)
    status_f1 = _macro_f1(status_pairs)
    exact_pairs = [
        (
            bool(record.exact_or_synonym_gold_positive),
            bool(record.exact_or_synonym_predicted_positive),
        )
        for record in reviewed
        if record.exact_or_synonym_gold_positive is not None
        and record.exact_or_synonym_predicted_positive is not None
    ]
    strict_values = [
        record.strict_false_positive
        for record in reviewed
        if record.strict_requirement
    ]
    claim_pairs = [
        (record.resume_claim_supported, record.resume_claim_predicted)
        for record in reviewed
    ]
    transfer_pairs = [
        (record.transfer_correct, record.transfer_predicted) for record in reviewed
    ]
    transfer_credit_pairs = [
        (record.transfer_correct, record.must_have_positive_credit)
        for record in reviewed
    ]
    adversarial_values = [
        record.false_transfer
        for record in reviewed
        if record.adversarial_same_domain_negative
    ]
    correction_values = [
        bool(record.correction_propagated)
        for record in reviewed
        if record.correction_propagated is not None
    ]
    reproduction_values = [
        bool(record.reproduced)
        for record in reviewed
        if record.reproduced is not None
    ]
    metrics = UccmMetrics(
        exact_synonym_precision=_precision(exact_pairs),
        strict_false_positive_rate=_rate(strict_values),
        resume_claim_precision=_precision(claim_pairs),
        transfer_precision=_precision(transfer_pairs),
        transfer_must_have_credit_precision=_precision(transfer_credit_pairs),
        adversarial_false_transfer_rate=_rate(adversarial_values),
        concept_type_macro_f1=type_f1[0] if type_f1 is not None else None,
        match_status_macro_f1=status_f1[0] if status_f1 is not None else None,
        match_status_min_f1=status_f1[1] if status_f1 is not None else None,
        correction_propagation_rate=_rate(correction_values),
        deterministic_reproduction_rate=_rate(reproduction_values),
    )
    families = sorted({record.career_family for record in reviewed})
    levels = sorted({record.career_level for record in reviewed})
    stratum_counts = {
        f"{family}:{level}": sum(
            record.career_family == family and record.career_level == level
            for record in reviewed
        )
        for family in REQUIRED_CAREER_FAMILIES
        for level in REQUIRED_CAREER_LEVELS
    }
    concept_types = sorted(
        {record.concept_type_gold for record in reviewed if record.concept_type_gold}
    )
    match_statuses = sorted(
        {record.match_status_gold for record in reviewed if record.match_status_gold}
    )
    metric_denominators = {
        "exact_synonym_precision": _predicted_count(exact_pairs),
        "strict_false_positive_rate": len(strict_values),
        "resume_claim_precision": _predicted_count(claim_pairs),
        "transfer_precision": _predicted_count(transfer_pairs),
        "transfer_must_have_credit_precision": _predicted_count(
            transfer_credit_pairs
        ),
        "adversarial_false_transfer_rate": len(adversarial_values),
        "concept_type_macro_f1": len(type_pairs),
        "match_status_macro_f1": len(status_pairs),
        "match_status_min_f1": len(status_pairs),
        "correction_propagation_rate": len(correction_values),
        "deterministic_reproduction_rate": len(reproduction_values),
    }
    failed: list[str] = []
    if not manifest.reviewed or not manifest.reviewer_ids:
        failed.append("gold_set_not_reviewed")
    if any(
        count < MINIMUM_RECORDS_PER_STRATUM for count in stratum_counts.values()
    ):
        failed.append("insufficient_career_coverage")
    if not REQUIRED_CONCEPT_TYPES.issubset(concept_types):
        failed.append("insufficient_concept_type_coverage")
    if not REQUIRED_MATCH_STATUSES.issubset(match_statuses):
        failed.append("insufficient_match_status_coverage")
    for name, minimum in MINIMUM_GATE_DENOMINATORS.items():
        if metric_denominators[name] < minimum:
            failed.append(f"{name}_insufficient_denominator")
    _threshold(
        failed,
        name="exact_synonym_precision",
        value=metrics.exact_synonym_precision,
        minimum=0.98,
    )
    _threshold(
        failed,
        name="strict_false_positive_rate",
        value=metrics.strict_false_positive_rate,
        maximum=0.005,
    )
    _threshold(
        failed,
        name="resume_claim_precision",
        value=metrics.resume_claim_precision,
        minimum=0.995,
    )
    _threshold(
        failed,
        name="transfer_precision",
        value=metrics.transfer_precision,
        minimum=0.92,
    )
    _threshold(
        failed,
        name="transfer_must_have_credit_precision",
        value=metrics.transfer_must_have_credit_precision,
        minimum=0.97,
    )
    _threshold(
        failed,
        name="adversarial_false_transfer_rate",
        value=metrics.adversarial_false_transfer_rate,
        maximum=0.03,
    )
    _threshold(
        failed,
        name="concept_type_macro_f1",
        value=metrics.concept_type_macro_f1,
        minimum=0.93,
    )
    _threshold(
        failed,
        name="match_status_macro_f1",
        value=metrics.match_status_macro_f1,
        minimum=0.88,
    )
    _threshold(
        failed,
        name="match_status_min_f1",
        value=metrics.match_status_min_f1,
        minimum=0.80,
    )
    _threshold(
        failed,
        name="correction_propagation_rate",
        value=metrics.correction_propagation_rate,
        minimum=1.0,
    )
    _threshold(
        failed,
        name="deterministic_reproduction_rate",
        value=metrics.deterministic_reproduction_rate,
        minimum=1.0,
    )
    failed = sorted(set(failed))
    checksum_payload = {
        "evaluation_revision": "uccm-eval-v1",
        "manifest": manifest.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in reviewed],
        "metrics": metrics.model_dump(mode="json"),
        "stratum_counts": stratum_counts,
        "concept_types": concept_types,
        "match_statuses": match_statuses,
        "metric_denominators": metric_denominators,
        "failed_gates": failed,
    }
    checksum = hashlib.sha256(
        json.dumps(
            checksum_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return UccmEvaluationReport(
        gold_set_revision=manifest.revision,
        reviewed_record_count=len(reviewed),
        metrics=metrics,
        career_families=families,
        career_levels=levels,
        stratum_counts=stratum_counts,
        concept_types=concept_types,
        match_statuses=match_statuses,
        metric_denominators=metric_denominators,
        failed_gates=failed,
        eligible=not failed,
        checksum=checksum,
    )


def load_gold_jsonl(path: str | Path) -> list[UccmEvalRecord]:
    records: list[UccmEvalRecord] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            records.append(UccmEvalRecord.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"invalid UCCM gold record on line {line_number}") from exc
    return records


def build_activation_report(
    evaluation: UccmEvaluationReport,
    manifest: GoldSetManifest,
    *,
    report_revision: str,
    taxonomy_revision: str,
    assertion_policy_revision: str,
    extraction_policy_revision: str,
    matching_policy_revision: str,
    generated_at: datetime,
    expires_at: datetime,
) -> UccmActivationReport:
    """Seal an offline evaluation for the runtime's fail-closed release policy."""
    report = UccmActivationReport(
        report_revision=report_revision,
        evaluation_revision=evaluation.evaluation_revision,
        gold_set_revision=evaluation.gold_set_revision,
        reviewed=manifest.reviewed,
        reviewer_ids=manifest.reviewer_ids,
        generated_at=generated_at,
        expires_at=expires_at,
        taxonomy_revision=taxonomy_revision,
        assertion_policy_revision=assertion_policy_revision,
        extraction_policy_revision=extraction_policy_revision,
        matching_policy_revision=matching_policy_revision,
        reviewed_record_count=evaluation.reviewed_record_count,
        career_families=evaluation.career_families,
        career_levels=evaluation.career_levels,
        stratum_counts=evaluation.stratum_counts,
        concept_types=evaluation.concept_types,
        match_statuses=evaluation.match_statuses,
        metric_denominators=evaluation.metric_denominators,
        metrics=UccmActivationMetrics.model_validate(
            evaluation.metrics.model_dump(mode="json")
        ),
        failed_gates=evaluation.failed_gates,
        eligible=evaluation.eligible,
    )
    return seal_activation_report(report)
