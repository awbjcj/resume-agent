"""Conservative, source-preserving UCCM concept typing."""

from __future__ import annotations

import hashlib
import json
import re
from asyncio import Semaphore
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, ValidationError, model_validator

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.graph_models import ConceptType

TERM_TYPING_POLICY_REVISION = "term-typing-v1"
UNKNOWN_CONCEPT_TYPE = "unknown"
TermConceptType = ConceptType | Literal["unknown"]
TermSourceKind = Literal[
    "profile_skill",
    "profile_fact",
    "job_description",
    "job_criteria",
    "manual",
]
DecisionSource = Literal["rule", "governed", "model", "correction", "unknown"]

_SPACE = re.compile(r"\s+")
_CREDENTIAL = re.compile(
    r"\b(certified|certification|certificate|licen[cs](?:e|ed|ure)|cpa|cfa|pmp)\b",
    re.IGNORECASE,
)
_DEGREE = re.compile(
    r"\b(bachelor(?:'s)?|master(?:'s)?|doctorate|ph\.?d\.?|degree|diploma)\b",
    re.IGNORECASE,
)
_EXPERIENCE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*[-+])?\s+"
    r"years?\b|\bminimum experience\b",
    re.IGNORECASE,
)
_WORK_CONTEXT = re.compile(
    r"\b(remote|hybrid|on[ -]?site|full[ -]?time|part[ -]?time|night shift|"
    r"weekend|travel|relocat(?:e|ion)|work authorization|visa sponsorship|"
    r"security clearance|citizenship|physical demands?)\b",
    re.IGNORECASE,
)
_STANDARD = re.compile(
    r"\b(iso(?:\s*\d+)?|gaap|ifrs|soc\s*2|hipaa|gdpr|pci[ -]?dss)\b",
    re.IGNORECASE,
)
_METHOD = re.compile(
    r"\b(scrum|kanban|agile|six sigma|lean|design thinking|test[- ]driven development)\b",
    re.IGNORECASE,
)
_LANGUAGE = re.compile(
    r"^(english|spanish|french|german|mandarin|cantonese|japanese|korean|"
    r"arabic|hindi|portuguese|italian)$",
    re.IGNORECASE,
)
_TOOLS = frozenset(
    {
        "aws",
        "azure",
        "docker",
        "excel",
        "git",
        "github",
        "java",
        "javascript",
        "jira",
        "kubernetes",
        "power bi",
        "python",
        "react",
        "salesforce",
        "sap",
        "sql",
        "tableau",
        "terraform",
    }
)


def normalize_term(value: str) -> str:
    return _SPACE.sub(" ", value).strip().casefold()


class TermSource(ExtensibleModel):
    source_kind: TermSourceKind
    source_id: str = Field(min_length=1)
    source_text: str | None = None
    original_text: str = Field(min_length=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> TermSource:
        if (self.start is None) != (self.end is None):
            raise ValueError("source span requires both start and end")
        if self.start is None:
            return self
        if self.source_text is None:
            raise ValueError("source span requires source_text")
        if self.end is None or self.end < self.start:
            raise ValueError("source span end precedes start")
        if self.source_text[self.start : self.end] != self.original_text:
            raise ValueError("source span does not match original_text")
        return self

    @classmethod
    def from_text(
        cls,
        *,
        source_kind: TermSourceKind,
        source_id: str,
        source_text: str,
        original_text: str,
        start: int,
    ) -> TermSource:
        return cls(
            source_kind=source_kind,
            source_id=source_id,
            source_text=source_text,
            original_text=original_text,
            start=start,
            end=start + len(original_text),
        )

    @classmethod
    def without_offsets(
        cls,
        *,
        source_kind: TermSourceKind,
        source_id: str,
        original_text: str,
    ) -> TermSource:
        return cls(
            source_kind=source_kind,
            source_id=source_id,
            original_text=original_text,
        )


class TermTypeSuggestion(ExtensibleModel):
    concept_type: ConceptType
    confidence: float = Field(ge=0.0, le=1.0)
    concept_id: str | None = None


@runtime_checkable
class TermTypeAssistant(Protocol):
    def classify(self, source: TermSource) -> object: ...


@runtime_checkable
class AsyncTermTypeAssistant(TermTypeAssistant, Protocol):
    async def aclassify(
        self, source: TermSource, *, sem: Semaphore
    ) -> TermTypeSuggestion: ...


class TermTypingDecision(ExtensibleModel):
    id: str
    source: TermSource
    normalized_text: str
    concept_type: TermConceptType
    concept_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    decision_source: DecisionSource
    reason_code: str
    policy_revision: str = TERM_TYPING_POLICY_REVISION

    @property
    def original_text(self) -> str:
        return self.source.original_text

    @property
    def start(self) -> int | None:
        return self.source.start

    @property
    def end(self) -> int | None:
        return self.source.end


def _decision_id(source: TermSource, policy_revision: str) -> str:
    payload = json.dumps(
        {
            "source_kind": source.source_kind,
            "source_id": source.source_id,
            "start": source.start,
            "end": source.end,
            "original_text": source.original_text,
            "policy_revision": policy_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"term:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _result(
    source: TermSource,
    *,
    concept_type: TermConceptType,
    confidence: float,
    decision_source: DecisionSource,
    reason_code: str,
    concept_id: str | None = None,
    policy_revision: str = TERM_TYPING_POLICY_REVISION,
) -> TermTypingDecision:
    return TermTypingDecision(
        id=_decision_id(source, policy_revision),
        source=source,
        normalized_text=normalize_term(source.original_text),
        concept_type=concept_type,
        concept_id=concept_id,
        confidence=confidence,
        decision_source=decision_source,
        reason_code=reason_code,
        policy_revision=policy_revision,
    )


def _rule_type(normalized: str) -> tuple[ConceptType, str] | None:
    if _CREDENTIAL.search(normalized) or _DEGREE.search(normalized):
        return "credential", "credential_rule"
    if _EXPERIENCE.search(normalized):
        return "requirement", "experience_requirement_rule"
    if _WORK_CONTEXT.search(normalized):
        return "work_context", "work_context_rule"
    if _LANGUAGE.fullmatch(normalized):
        return "language", "language_rule"
    if _STANDARD.search(normalized):
        return "standard", "standard_rule"
    if _METHOD.search(normalized):
        return "method", "method_rule"
    if normalized in _TOOLS:
        return "tool_technology", "tool_rule"
    return None


def type_term(
    source: TermSource,
    *,
    canonical_text: str | None = None,
    governed_types: Mapping[str, tuple[str, ConceptType]] | None = None,
    assistant: TermTypeAssistant | None = None,
    minimum_model_confidence: float = 0.7,
    policy_revision: str = TERM_TYPING_POLICY_REVISION,
) -> TermTypingDecision:
    normalized = normalize_term(source.original_text)
    governed = (governed_types or {}).get(normalized)
    if governed is not None:
        concept_id, concept_type = governed
        return _result(
            source,
            concept_type=concept_type,
            concept_id=concept_id,
            confidence=1.0,
            decision_source="governed",
            reason_code="governed_concept",
            policy_revision=policy_revision,
        )
    rule = _rule_type(normalized)
    if rule is None and canonical_text is not None:
        rule = _rule_type(normalize_term(canonical_text))
        if rule is not None:
            rule = (rule[0], f"canonical_{rule[1]}")
    if rule is not None:
        concept_type, reason_code = rule
        return _result(
            source,
            concept_type=concept_type,
            confidence=1.0,
            decision_source="rule",
            reason_code=reason_code,
            policy_revision=policy_revision,
        )
    if assistant is None:
        return _result(
            source,
            concept_type="unknown",
            confidence=0.0,
            decision_source="unknown",
            reason_code="ambiguous",
            policy_revision=policy_revision,
        )
    try:
        suggestion = TermTypeSuggestion.model_validate(assistant.classify(source))
    except (ValidationError, TypeError, ValueError):
        return _result(
            source,
            concept_type="unknown",
            confidence=0.0,
            decision_source="unknown",
            reason_code="invalid_model_output",
            policy_revision=policy_revision,
        )
    except Exception:
        return _result(
            source,
            concept_type="unknown",
            confidence=0.0,
            decision_source="unknown",
            reason_code="assistant_failure",
            policy_revision=policy_revision,
        )
    if suggestion.confidence < minimum_model_confidence:
        return _result(
            source,
            concept_type="unknown",
            confidence=suggestion.confidence,
            decision_source="unknown",
            reason_code="low_model_confidence",
            policy_revision=policy_revision,
        )
    return _result(
        source,
        concept_type=suggestion.concept_type,
        concept_id=suggestion.concept_id,
        confidence=suggestion.confidence,
        decision_source="model",
        reason_code="model_assisted",
        policy_revision=policy_revision,
    )


def type_terms(
    sources: Sequence[TermSource],
    *,
    governed_types: Mapping[str, tuple[str, ConceptType]] | None = None,
    canonical_texts: Mapping[str, str] | None = None,
    assistant: TermTypeAssistant | None = None,
    minimum_model_confidence: float = 0.7,
    policy_revision: str = TERM_TYPING_POLICY_REVISION,
) -> list[TermTypingDecision]:
    return [
        type_term(
            source,
            canonical_text=(canonical_texts or {}).get(source.source_id),
            governed_types=governed_types,
            assistant=assistant,
            minimum_model_confidence=minimum_model_confidence,
            policy_revision=policy_revision,
        )
        for source in sources
    ]
