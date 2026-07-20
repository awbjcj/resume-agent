"""The prompt registry projects every application-owned Agno prompt."""

from typing import cast

from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.prompts.registry import PROMPT_SPECS, SPECS_BY_KEY, spec_for


def _instructions(runner: Runner) -> list[str]:
    return list(cast(AgentRunner, runner)._agent.instructions)


VALID_STAGES = {
    "tailoring",
    "review",
    "cover-letter",
    "discovery",
    "profile",
    "interview",
    "email",
}


def test_keys_are_unique_and_lookup_matches() -> None:
    keys = [spec.key for spec in PROMPT_SPECS]
    assert len(keys) == len(set(keys))
    assert set(SPECS_BY_KEY) == set(keys)
    assert spec_for("tailor-writer") is SPECS_BY_KEY["tailor-writer"]
    assert spec_for("missing") is None


def test_every_spec_is_complete() -> None:
    for spec in PROMPT_SPECS:
        assert spec.stage in VALID_STAGES, spec.key
        assert spec.title and spec.description, spec.key
        assert spec.instructions, spec.key
        assert all(isinstance(line, str) and line for line in spec.instructions), (
            spec.key
        )


def test_fact_check_is_the_only_locked_agent() -> None:
    assert {spec.key for spec in PROMPT_SPECS if not spec.editable} == {
        "reviewer-fact-check"
    }


def test_registry_projects_real_instruction_constants() -> None:
    from resume_agent.discovery import fit
    from resume_agent.gmail import classify
    from resume_agent.tailor import agents as tailor_agents

    assert SPECS_BY_KEY["fit-score"].instructions == tuple(fit._INSTRUCTIONS)
    assert SPECS_BY_KEY["reviewer-fact-check"].instructions == tuple(
        tailor_agents._reviewer_instructions("fact-check")
    )
    assert SPECS_BY_KEY["reviewer-merged-advisory"].instructions == tuple(
        tailor_agents._MERGED_ADVISORY_BASE_INSTRUCTIONS
    )
    assert SPECS_BY_KEY["email-classifier"].instructions == tuple(
        classify._CLASSIFIER_INSTRUCTIONS
    )


def test_interviewer_registers_the_persona_core() -> None:
    from resume_agent.interview.agent import _PERSONA_CORE

    assert SPECS_BY_KEY["interviewer"].instructions == tuple(_PERSONA_CORE)


def test_composed_registry_entries_match_their_built_agents() -> None:
    from resume_agent.tailor.agents import build_reviewer_agent, build_tailor_agent
    from resume_agent.tailor.match_plan import build_match_plan_agent

    assert SPECS_BY_KEY["tailor-writer"].instructions == tuple(
        _instructions(build_tailor_agent())
    )
    assert SPECS_BY_KEY["reviewer-recruiter"].instructions == tuple(
        _instructions(build_reviewer_agent("recruiter"))
    )
    assert SPECS_BY_KEY["match-plan"].instructions == tuple(
        _instructions(build_match_plan_agent())
    )
