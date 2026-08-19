from __future__ import annotations

import json

from resume_agent.taxonomy.term_typing import TermSource, type_term


class _Result:
    def __init__(self, content):
        self.content = content


class _Runner:
    def __init__(self, content):
        self.content = content
        self.prompts: list[str] = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return _Result(self.content)

    async def arun(self, prompt):
        return self.run(prompt)


def test_model_adapter_uses_schema_boundary_for_an_ambiguous_phrase():
    from resume_agent.taxonomy.term_assistant import ModelTermTypeAssistant
    from resume_agent.taxonomy.term_typing import TermTypeSuggestion

    runner = _Runner(
        TermTypeSuggestion(concept_type="capability", confidence=0.92)
    )
    assistant = ModelTermTypeAssistant(runner)
    source = TermSource.without_offsets(
        source_kind="job_criteria",
        source_id="job:42:nice:0",
        original_text="Stakeholder leadership",
    )

    decision = type_term(source, assistant=assistant)

    assert decision.concept_type == "capability"
    assert decision.decision_source == "model"
    prompt = json.loads(runner.prompts[0])
    assert prompt["term"] == "Stakeholder leadership"
    assert prompt["sourceKind"] == "job_criteria"
    assert prompt["policyRevision"] == "term-typing-v1"


def test_model_adapter_invalid_output_remains_observable_unknown():
    from resume_agent.taxonomy.term_assistant import ModelTermTypeAssistant

    source = TermSource.without_offsets(
        source_kind="job_criteria",
        source_id="job:42:nice:0",
        original_text="Stakeholder leadership",
    )
    decision = type_term(
        source,
        assistant=ModelTermTypeAssistant(_Runner({"concept_type": "mystery"})),
    )

    assert decision.concept_type == "unknown"
    assert decision.reason_code == "invalid_model_output"
