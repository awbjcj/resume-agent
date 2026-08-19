"""Deterministic typed-requirement binding after lean JD extraction."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from resume_agent.models.job import JobCriteria
from resume_agent.models.requirements import (
    JOB_EXTRACTION_POLICY_REVISION,
    EvidenceExpectation,
    JobRequirement,
    LegacyRequirementSource,
    RequirementKind,
    RequirementProvenance,
    RequirementReconciliationIssue,
    RequirementStrictness,
)
from resume_agent.taxonomy.identity import legacy_concept_id, typed_concept_id
from resume_agent.taxonomy.term_corrections import (
    TermTypeCorrection,
    apply_term_type_corrections,
)
from resume_agent.taxonomy.term_typing import (
    AsyncTermTypeAssistant,
    TermSource,
    TermTypeAssistant,
    TermTypeSuggestion,
    TermTypingDecision,
    type_term,
)
from resume_agent.tracking.match_gap import normalize_skill

_PRODUCT_FAMILIES = frozenset({"aws", "azure", "gcp", "microsoft office"})
_AVAILABILITY_TERMS = re.compile(
    r"\b(work authorization|visa|sponsorship|citizenship|security clearance|"
    r"remote|hybrid|on[ -]?site|location|relocat(?:e|ion))\b",
    re.IGNORECASE,
)
_PHYSICAL_TERMS = re.compile(
    r"\b(lift|standing|physical demands?|outdoors?|hazardous|shift work)\b",
    re.IGNORECASE,
)
_EDUCATION_TERMS = re.compile(
    r"\b(bachelor(?:'s)?|master(?:'s)?|doctorate|ph\.?d\.?|degree|diploma)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


@dataclass(frozen=True)
class _RawRequirement:
    text: str
    legacy_source: LegacyRequirementSource
    legacy_order: int
    preferred: bool = False
    kind_override: RequirementKind | None = None
    context: tuple[tuple[str, str], ...] = ()


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _locate(text: str, jd_text: str | None) -> tuple[int, int] | None:
    if jd_text is None:
        return None
    match = re.search(re.escape(text), jd_text, re.IGNORECASE)
    return match.span() if match is not None else None


def _source_for(
    raw: _RawRequirement,
    *,
    job_id: str,
    jd_text: str | None,
    legacy: bool,
    explicit_span: tuple[int, int] | None = None,
) -> tuple[TermSource, RequirementProvenance]:
    span = explicit_span or _locate(raw.text, jd_text)
    if legacy:
        provenance: RequirementProvenance = "legacy_list_item"
        span = None
    elif span is None:
        provenance = "unlocated_extraction"
    else:
        provenance = "exact_span"
    source = (
        TermSource.from_text(
            source_kind="job_description",
            source_id=f"job:{job_id}:{raw.legacy_source}:{raw.legacy_order}",
            source_text=jd_text or "",
            original_text=(jd_text or "")[span[0] : span[1]],
            start=span[0],
        )
        if span is not None
        else TermSource.without_offsets(
            source_kind="job_criteria",
            source_id=f"job:{job_id}:{raw.legacy_source}:{raw.legacy_order}",
            original_text=raw.text,
        )
    )
    return source, provenance


def _experience_phrase(years: int, jd_text: str) -> tuple[str, int, int] | None:
    word = _NUMBER_WORDS.get(years)
    choices = [str(years), *([word] if word else [])]
    pattern = rf"\b(?:{'|'.join(map(re.escape, choices))})\s*\+?\s+years?"
    pattern += r"(?:\s+of\s+(?:relevant\s+)?experience)?\b"
    match = re.search(pattern, jd_text, re.IGNORECASE)
    if match is None:
        return None
    return match.group(), match.start(), match.end()


def _kind(raw: _RawRequirement, decision: TermTypingDecision) -> RequirementKind:
    if raw.kind_override is not None:
        return raw.kind_override
    if _EDUCATION_TERMS.search(raw.text):
        return "education_required"
    if decision.concept_type == "credential":
        return "credential_preferred" if raw.preferred else "credential_required"
    if _AVAILABILITY_TERMS.search(raw.text):
        return "availability_or_location"
    if _PHYSICAL_TERMS.search(raw.text):
        return "physical_or_environmental"
    if raw.legacy_source == "nice":
        return "preferred"
    if raw.legacy_source == "tech":
        return "responsibility"
    return "must_have"


def _strictness(
    raw: _RawRequirement, decision: TermTypingDecision
) -> RequirementStrictness:
    if decision.concept_type == "credential":
        return "credential"
    if decision.concept_type in {"method", "standard"}:
        return "method_or_standard"
    if decision.concept_type == "tool_technology":
        return (
            "product_family"
            if normalize_skill(raw.text) in _PRODUCT_FAMILIES
            else "exact_product"
        )
    if decision.concept_type in {
        "capability",
        "skill",
        "knowledge",
        "work_activity",
        "task",
    }:
        return "capability"
    return "contextual"


def _expectation(
    kind: RequirementKind, decision: TermTypingDecision
) -> EvidenceExpectation:
    if kind in {
        "credential_required",
        "credential_preferred",
        "availability_or_location",
        "education_required",
    }:
        return "verified_fact"
    if decision.concept_type == "unknown":
        return "unknown"
    return "candidate_evidence"


def _requirement_id(
    *,
    job_id: str,
    source_text: str,
    source_start: int | None,
    source_end: int | None,
    legacy_source: LegacyRequirementSource,
    legacy_order: int,
    kind: RequirementKind,
    strictness: RequirementStrictness,
) -> str:
    return "requirement:" + _stable_hash(
        {
            "job_id": job_id,
            "source_text": source_text,
            "source_start": source_start,
            "source_end": source_end,
            "legacy_source": legacy_source,
            "legacy_order": legacy_order,
            "kind": kind,
            "strictness": strictness,
            "policy": JOB_EXTRACTION_POLICY_REVISION,
        }
    )


def _bind_one(
    raw: _RawRequirement,
    *,
    job_id: str,
    jd_text: str | None,
    taxonomy_revision: str,
    legacy: bool,
    explicit_span: tuple[int, int] | None = None,
    assistant: TermTypeAssistant | None = None,
    aliases: Mapping[str, str] | None = None,
    term_corrections: list[TermTypeCorrection] | None = None,
) -> JobRequirement:
    source, provenance = _source_for(
        raw,
        job_id=job_id,
        jd_text=jd_text,
        legacy=legacy,
        explicit_span=explicit_span,
    )
    normalized = normalize_skill(source.original_text)
    canonical = (aliases or {}).get(normalized, normalized)
    decision = apply_term_type_corrections(
        [
            type_term(
                source,
                canonical_text=canonical,
                assistant=assistant,
            )
        ],
        term_corrections or [],
    )[0]
    kind = _kind(raw, decision)
    strictness = _strictness(raw, decision)
    source_text = source.original_text
    context = dict(raw.context)
    if kind in {"availability_or_location", "physical_or_environmental"}:
        context.setdefault("constraint", source_text)
    if decision.concept_type == "unknown":
        concept_id = None
    elif decision.concept_type in {
        "capability",
        "skill",
        "knowledge",
        "work_activity",
        "task",
        "method",
        "standard",
        "tool_technology",
        "artifact",
        "work_style",
        "language",
    }:
        concept_id = legacy_concept_id(canonical)
    else:
        concept_id = typed_concept_id(decision.concept_type, source_text)
    return JobRequirement(
        id=_requirement_id(
            job_id=job_id,
            source_text=source_text,
            source_start=source.start,
            source_end=source.end,
            legacy_source=raw.legacy_source,
            legacy_order=raw.legacy_order,
            kind=kind,
            strictness=strictness,
        ),
        job_id=job_id,
        source_text=source_text,
        source_start=source.start,
        source_end=source.end,
        provenance=provenance,
        parsed_concept_id=concept_id,
        parsed_concept_label=canonical,
        concept_type=decision.concept_type,
        requirement_kind=kind,
        strictness=strictness,
        context=context,
        importance=1.0 if not raw.preferred else 0.6,
        evidence_expectation=_expectation(kind, decision),
        extraction_confidence=decision.confidence,
        taxonomy_revision=taxonomy_revision,
        term_decision_id=decision.id,
        legacy_source=raw.legacy_source,
        legacy_order=raw.legacy_order,
        exact_non_substitutable=strictness in {"credential", "exact_product"},
        failure_reason=(
            decision.reason_code if decision.concept_type == "unknown" else None
        ),
    )


def _legacy_raw(criteria: JobCriteria) -> list[_RawRequirement]:
    fields: tuple[tuple[LegacyRequirementSource, list[str], bool], ...] = (
        ("must", criteria.must_have_skills, False),
        ("nice", criteria.nice_to_have_skills, True),
        ("tech", criteria.tech_stack, False),
    )
    return [
        _RawRequirement(
            text=text,
            legacy_source=source,
            legacy_order=index,
            preferred=preferred,
        )
        for source, values, preferred in fields
        for index, text in enumerate(values)
        if text.strip()
    ]


def adapt_legacy_requirements(
    criteria: JobCriteria,
    *,
    job_id: int | str,
    taxonomy_revision: str,
    aliases: Mapping[str, str] | None = None,
    term_corrections: list[TermTypeCorrection] | None = None,
) -> list[JobRequirement]:
    return [
        _bind_one(
            raw,
            job_id=str(job_id),
            jd_text=None,
            taxonomy_revision=taxonomy_revision,
            legacy=True,
            aliases=aliases,
            term_corrections=term_corrections,
        )
        for raw in _legacy_raw(criteria)
    ]


def project_legacy_criteria(
    requirements: list[JobRequirement],
) -> dict[str, list[str]]:
    result = {
        "must_have_skills": [],
        "nice_to_have_skills": [],
        "tech_stack": [],
    }
    field_for = {
        "must": "must_have_skills",
        "nice": "nice_to_have_skills",
        "tech": "tech_stack",
    }
    for item in sorted(
        requirements,
        key=lambda value: (
            {"must": 0, "nice": 1, "tech": 2, "derived": 3}[value.legacy_source],
            value.legacy_order,
            value.id,
        ),
    ):
        field = field_for.get(item.legacy_source)
        if field is not None:
            result[field].append(item.source_text)
    return result


def _explicit_requirements(
    criteria: JobCriteria,
    *,
    jd_text: str,
) -> list[tuple[_RawRequirement, tuple[int, int] | None]]:
    raw = _legacy_raw(criteria)
    explicit: list[tuple[_RawRequirement, tuple[int, int] | None]] = [
        (item, None) for item in raw
    ]
    derived_order = 0
    if criteria.yoe_min is not None:
        located = _experience_phrase(criteria.yoe_min, jd_text)
        text = located[0] if located else f"{criteria.yoe_min} years of experience"
        explicit.append(
            (
                _RawRequirement(
                    text=text,
                    legacy_source="derived",
                    legacy_order=derived_order,
                    kind_override="experience_required",
                    context=(("minimum_years", str(criteria.yoe_min)),),
                ),
                (located[1], located[2]) if located else None,
            )
        )
        derived_order += 1
    if criteria.employment_type is not None:
        employment_text = criteria.employment_type.value.replace("_", "-")
        explicit.append(
            (
                _RawRequirement(
                    text=employment_text,
                    legacy_source="derived",
                    legacy_order=derived_order,
                    kind_override="context",
                    context=(("employment_type", criteria.employment_type.value),),
                ),
                None,
            )
        )
        derived_order += 1
    for value, context_key in (
        (criteria.remote_policy, "remote_policy"),
        (criteria.location, "location"),
    ):
        if value:
            explicit.append(
                (
                    _RawRequirement(
                        text=value,
                        legacy_source="derived",
                        legacy_order=derived_order,
                        kind_override="availability_or_location",
                        context=((context_key, value),),
                    ),
                    None,
                )
            )
            derived_order += 1
    return explicit


def bind_job_requirements(
    criteria: JobCriteria,
    *,
    job_id: int | str,
    jd_text: str,
    taxonomy_revision: str,
    assistant: TermTypeAssistant | None = None,
    aliases: Mapping[str, str] | None = None,
    term_corrections: list[TermTypeCorrection] | None = None,
) -> JobCriteria:
    explicit = _explicit_requirements(criteria, jd_text=jd_text)
    requirements = [
        _bind_one(
            item,
            job_id=str(job_id),
            jd_text=jd_text,
            taxonomy_revision=taxonomy_revision,
            legacy=False,
            explicit_span=span,
            assistant=assistant,
            aliases=aliases,
            term_corrections=term_corrections,
        )
        for item, span in explicit
    ]
    issues = [
        RequirementReconciliationIssue(
            code="source_span_not_found",
            requirement_id=item.id,
            message="Could not locate extracted criterion in the job description",
        )
        for item in requirements
        if item.provenance == "unlocated_extraction"
    ]
    projection = project_legacy_criteria(requirements)
    expected = {
        "must_have_skills": criteria.must_have_skills,
        "nice_to_have_skills": criteria.nice_to_have_skills,
        "tech_stack": criteria.tech_stack,
    }
    if projection != expected:
        issues.append(
            RequirementReconciliationIssue(
                code="legacy_projection_mismatch",
                message="Typed requirements do not reproduce the legacy criteria lists",
            )
        )
    revision = _stable_hash(
        {
            "requirements": [item.model_dump(mode="json") for item in requirements],
            "taxonomy_revision": taxonomy_revision,
            "policy": JOB_EXTRACTION_POLICY_REVISION,
        }
    )
    return criteria.model_copy(
        update={
            "typed_requirements": requirements,
            "extraction_policy_revision": JOB_EXTRACTION_POLICY_REVISION,
            "job_extraction_revision": revision,
            "requirement_reconciliation_issues": issues,
        }
    )


class _SuggestionAssistant:
    def __init__(self, suggestions: Mapping[str, TermTypeSuggestion]):
        self._suggestions = suggestions

    def classify(self, source: TermSource) -> object:
        return self._suggestions[source.source_id]


async def abind_job_requirements(
    criteria: JobCriteria,
    *,
    job_id: int | str,
    jd_text: str,
    taxonomy_revision: str,
    assistant: AsyncTermTypeAssistant | None,
    sem: asyncio.Semaphore,
    aliases: Mapping[str, str] | None = None,
    term_corrections: list[TermTypeCorrection] | None = None,
) -> JobCriteria:
    """Bind requirements while keeping optional model calls in the async leaf."""
    if assistant is None:
        return bind_job_requirements(
            criteria,
            job_id=job_id,
            jd_text=jd_text,
            taxonomy_revision=taxonomy_revision,
            aliases=aliases,
            term_corrections=term_corrections,
        )

    pending: list[TermSource] = []
    for raw, span in _explicit_requirements(criteria, jd_text=jd_text):
        source, _ = _source_for(
            raw,
            job_id=str(job_id),
            jd_text=jd_text,
            legacy=False,
            explicit_span=span,
        )
        normalized = normalize_skill(source.original_text)
        canonical = (aliases or {}).get(normalized, normalized)
        decision = apply_term_type_corrections(
            [type_term(source, canonical_text=canonical)],
            term_corrections or [],
        )[0]
        if (
            decision.concept_type == "unknown"
            and decision.decision_source != "correction"
        ):
            pending.append(source)

    suggestions = await asyncio.gather(
        *(assistant.aclassify(source, sem=sem) for source in pending)
    )
    cached = _SuggestionAssistant(
        dict(zip((item.source_id for item in pending), suggestions))
    )
    return bind_job_requirements(
        criteria,
        job_id=job_id,
        jd_text=jd_text,
        taxonomy_revision=taxonomy_revision,
        assistant=cached,
        aliases=aliases,
        term_corrections=term_corrections,
    )
