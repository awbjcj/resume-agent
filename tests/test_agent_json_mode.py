"""Regression guard: structured-output agents pick the right output mode per provider.

OpenAI-compatible providers such as DeepSeek expose no native/json_schema
structured outputs (``supports_native_structured_outputs = False``), so an
``output_schema`` is honoured only when the agent runs with
``use_json_mode=True``. Without it, DeepSeek intermittently returns prose that
agno cannot parse, falls back to the raw ``str``, and the pipeline raises
``TypeError: Expected <Schema> from agent, got str``.

Providers that *do* support native structured outputs (OpenAI, Anthropic) must
keep them (``use_json_mode=False``) — they are stricter than JSON mode. Builders
derive the flag from the model via ``use_json_mode_for``; these tests pin both
the helper's contract and that the builders thread it through.

Model construction here is offline: no network call is made, and a missing API
key resolves to ``None`` without error.
"""

from typing import cast

import pytest

import resume_agent.discovery.relevance as relevance_mod
from resume_agent.cover_letter.agents import build_cover_letter_agent
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.discovery.fit import build_fit_agent
from resume_agent.discovery.relevance import build_relevance_agent
from resume_agent.discovery.url_ingest.llm import build_url_extract_agent
from resume_agent.llm_runner import AgentRunner, build_model, use_json_mode_for
from resume_agent.profile.extractor import build_extractor_agent
from resume_agent.tailor.agents import build_reviewer_agent, build_tailor_agent

# (model_id, expected use_json_mode): DeepSeek needs JSON mode; the others keep
# native structured outputs.
_CASES = [
    pytest.param("deepseek:deepseek-chat", True, id="deepseek-json-mode"),
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
    assert cast(AgentRunner, build_extract_agent(model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_url_extract_builder_threads_json_mode(model_id, expected):
    assert cast(AgentRunner, build_url_extract_agent(model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_tailor_builder_threads_json_mode(model_id, expected):
    assert cast(AgentRunner, build_tailor_agent(model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_reviewer_builder_threads_json_mode(model_id, expected):
    assert cast(AgentRunner, build_reviewer_agent("hiring-manager", model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_cover_letter_builder_threads_json_mode(model_id, expected):
    assert cast(AgentRunner, build_cover_letter_agent(model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_profile_extractor_builder_threads_json_mode(model_id, expected):
    assert cast(AgentRunner, build_extractor_agent(model_id))._agent.use_json_mode is expected


@pytest.mark.parametrize("model_id, expected", _CASES)
def test_relevance_builder_threads_json_mode(monkeypatch, model_id, expected):
    # The builder short-circuits to None without a provider key; force one so we
    # actually construct the agent and can inspect it.
    monkeypatch.setattr(relevance_mod, "resolve_api_key", lambda _id: "test-key")
    runner = build_relevance_agent(model_id)
    assert runner is not None
    assert cast(AgentRunner, runner)._agent.use_json_mode is expected
