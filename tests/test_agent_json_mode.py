"""Regression guard: structured-output agents pick the right output mode per provider.

Every supported provider now exposes native/json_schema structured outputs, so
JSON mode is reserved for the one case that still needs it: a Claude schema that
exceeds Anthropic's grammar limits.

DeepSeek used to be the exception. On Chat Completions it advertised
``supports_native_structured_outputs = False``, so an ``output_schema`` was sent
as ``response_format={"type": "json_object"}`` -- which constrains "the output
must be JSON" but NOT "one well-formed, schema-conforming document and nothing
else". Live failures showed all three ways that leaks: malformed JSON, a second
document, and a literal ``<|DSML|>tool_calls`` block written into the content
channel instead of the tool channel. agno's parsers then left ``content`` a raw
``str`` and the pipeline raised ``Expected <Schema> from agent, got str``. On the
Responses API the schema rides ``text.format``, so DeepSeek keeps native
structured outputs like everyone else.

Builders derive the flag from the model and the output schema via
``use_json_mode_for``; these tests pin both the helper's contract and that the
builders thread it through.

Model construction here is offline: no network call is made, and a missing API
key resolves to ``None`` without error.
"""

from typing import cast

import pytest

import resume_tailor_harness.discovery.relevance as relevance_mod
from resume_tailor_harness.cover_letter.agents import build_cover_letter_agent
from resume_tailor_harness.discovery.extract import build_extract_agent
from resume_tailor_harness.discovery.fit import build_fit_agent
from resume_tailor_harness.discovery.relevance import build_relevance_agent
from resume_tailor_harness.discovery.url_ingest.llm import build_url_extract_agent
from resume_tailor_harness.llm_runner import AgentRunner, build_model, use_json_mode_for
from resume_tailor_harness.profile.extractor import build_extractor_agent
from resume_tailor_harness.tailor.agents import build_reviewer_agent, build_tailor_agent

# (model_id, expected use_json_mode): every provider keeps native structured
# outputs. JSON mode now has exactly one trigger, covered separately below:
# a Claude schema too large for Anthropic's grammar compiler.
_CASES = [
    pytest.param("deepseek:deepseek-v4-flash", False, id="deepseek-native"),
    pytest.param("claude-haiku-4-5-20251001", False, id="anthropic-native"),
    pytest.param("openai:gpt-4o-mini", False, id="openai-native"),
]


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_use_json_mode_for_matches_provider_capability(model_id, expected):
    assert use_json_mode_for(build_model(model_id)) is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_fit_builder_threads_json_mode(model_id, expected):
    assert cast(AgentRunner, build_fit_agent(model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_extract_builder_threads_json_mode(model_id, expected):
    assert (
        cast(AgentRunner, build_extract_agent(model_id))._agent.use_json_mode
        is expected
    )


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_url_extract_builder_threads_json_mode(model_id, expected):
    assert (
        cast(AgentRunner, build_url_extract_agent(model_id))._agent.use_json_mode
        is expected
    )


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_tailor_builder_threads_json_mode(model_id, expected):
    if model_id.startswith("claude-"):
        expected = True
    assert (
        cast(AgentRunner, build_tailor_agent(model_id))._agent.use_json_mode is expected
    )


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_reviewer_builder_threads_json_mode(model_id, expected):
    assert (
        cast(
            AgentRunner, build_reviewer_agent("hiring-manager", model_id)
        )._agent.use_json_mode
        is expected
    )


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_cover_letter_builder_threads_json_mode(model_id, expected):
    assert (
        cast(AgentRunner, build_cover_letter_agent(model_id))._agent.use_json_mode
        is expected
    )


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_profile_extractor_builder_threads_json_mode(model_id, expected):
    if model_id.startswith("claude-"):
        expected = True
    assert (
        cast(AgentRunner, build_extractor_agent(model_id))._agent.use_json_mode
        is expected
    )


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_relevance_builder_threads_json_mode(monkeypatch, model_id, expected):
    # The builder short-circuits to None without a provider key; force one so we
    # actually construct the agent and can inspect it.
    monkeypatch.setattr(relevance_mod, "resolve_api_key", lambda _id: "test-key")
    runner = build_relevance_agent(model_id)
    assert runner is not None
    assert cast(AgentRunner, runner)._agent.use_json_mode is expected
