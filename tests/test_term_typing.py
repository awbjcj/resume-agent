from __future__ import annotations

from dataclasses import dataclass

import pytest


def test_term_typing_preserves_source_and_keeps_ambiguity_unknown():
    from resume_agent.taxonomy.term_typing import TermSource, type_terms

    source_text = (
        "AWS Certified Solutions Architect, Python, five years of experience, "
        "remote, and leadership"
    )
    phrases = [
        "AWS Certified Solutions Architect",
        "Python",
        "five years of experience",
        "remote",
        "leadership",
    ]
    decisions = type_terms(
        [
            TermSource.from_text(
                source_kind="job_description",
                source_id="job:42",
                source_text=source_text,
                original_text=phrase,
                start=source_text.index(phrase),
            )
            for phrase in phrases
        ]
    )

    assert [decision.concept_type for decision in decisions] == [
        "credential",
        "tool_technology",
        "requirement",
        "work_context",
        "unknown",
    ]
    for phrase, decision in zip(phrases, decisions, strict=True):
        assert source_text[decision.start : decision.end] == phrase
        assert decision.original_text == phrase

    reordered = type_terms(list(reversed([decision.source for decision in decisions])))
    assert {decision.id for decision in reordered} == {
        decision.id for decision in decisions
    }


def test_term_source_rejects_a_span_that_does_not_match_original_text():
    from resume_agent.taxonomy.term_typing import TermSource

    with pytest.raises(ValueError, match="source span does not match original_text"):
        TermSource.from_text(
            source_kind="job_description",
            source_id="job:42",
            source_text="Python required",
            original_text="Python",
            start=1,
        )


@dataclass
class _FakeAssistant:
    result: object = None
    error: Exception | None = None
    calls: int = 0

    def classify(self, source):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def test_rules_run_before_the_optional_assistant():
    from resume_agent.taxonomy.term_typing import TermSource, type_term

    assistant = _FakeAssistant(result={"concept_type": "skill", "confidence": 1.0})
    decision = type_term(
        TermSource.without_offsets(
            source_kind="profile_skill",
            source_id="skill:python",
            original_text="Python",
        ),
        assistant=assistant,
    )

    assert decision.concept_type == "tool_technology"
    assert decision.decision_source == "rule"
    assert assistant.calls == 0


@pytest.mark.parametrize(
    ("assistant_result", "expected_type", "expected_reason"),
    [
        (
            {"concept_type": "capability", "confidence": 0.91},
            "capability",
            "model_assisted",
        ),
        (
            {"concept_type": "mystery", "confidence": 0.99},
            "unknown",
            "invalid_model_output",
        ),
        (
            {"concept_type": "capability", "confidence": 0.49},
            "unknown",
            "low_model_confidence",
        ),
    ],
)
def test_model_assistance_is_schema_and_confidence_gated(
    assistant_result,
    expected_type,
    expected_reason,
):
    from resume_agent.taxonomy.term_typing import TermSource, type_term

    decision = type_term(
        TermSource.without_offsets(
            source_kind="job_criteria",
            source_id="job:42:item:1",
            original_text="Stakeholder leadership",
        ),
        assistant=_FakeAssistant(result=assistant_result),
    )

    assert decision.concept_type == expected_type
    assert decision.reason_code == expected_reason


def test_provider_failure_is_observable_unknown():
    from resume_agent.taxonomy.term_typing import TermSource, type_term

    decision = type_term(
        TermSource.without_offsets(
            source_kind="job_criteria",
            source_id="job:42:item:1",
            original_text="Stakeholder leadership",
        ),
        assistant=_FakeAssistant(error=RuntimeError("offline")),
    )

    assert decision.concept_type == "unknown"
    assert decision.decision_source == "unknown"
    assert decision.reason_code == "assistant_failure"
