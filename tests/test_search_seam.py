import pytest

import resume_agent.llm_runner as llm_runner
from resume_agent.llm_runner import (
    DEEPSEEK_WEB_SEARCH_TOOL,
    OPENAI_WEB_SEARCH_TOOL,
    anthropic_web_search_tool,
    build_search_equipped,
    plan_search,
)


@pytest.mark.parametrize(
    ("model_id", "strategy"),
    [
        ("claude-opus-4-8", "native_anthropic"),
        ("gemini:gemini-2.0-flash", "native_gemini"),
        ("openai:gpt-4o", "native_openai"),
        ("deepseek:deepseek-v4-flash", "native_deepseek"),
    ],
)
def test_plan_auto_selects_provider_strategy(model_id, strategy):
    assert plan_search(model_id, "auto").strategy == strategy


def test_plan_tool_mode_forces_tool_for_anthropic():
    assert plan_search("claude-opus-4-8", "tool").strategy == "tool"


def test_plan_native_mode_rejects_unsupported_provider(monkeypatch):
    # Every provider the repo supports now has native web search, so this guard
    # is only reachable for a provider added to PROVIDERS without a native
    # strategy. Simulate that rather than deleting the coverage -- the branch is
    # what stops such a provider silently falling back to DuckDuckGo when the
    # operator explicitly asked for native.
    monkeypatch.setitem(llm_runner._NATIVE_SEARCH_STRATEGIES, "deepseek", None)
    with pytest.raises(ValueError, match="no native web search"):
        plan_search("deepseek:deepseek-v4-flash", "native")


def test_plan_auto_falls_back_to_tool_for_a_provider_without_native_search(monkeypatch):
    monkeypatch.setitem(llm_runner._NATIVE_SEARCH_STRATEGIES, "deepseek", None)
    assert plan_search("deepseek:deepseek-v4-flash", "auto").strategy == "tool"


def test_plan_off_mode_disables_search():
    assert plan_search("claude-opus-4-8", "off").strategy == "none"


def test_build_off_mode_disables_advisor():
    with pytest.raises(ValueError, match="disabled"):
        build_search_equipped("claude-opus-4-8", "off")


def test_build_search_equipped_anthropic_returns_dynamic_server_tool(monkeypatch):
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda _model_id: "")

    _model, tools = build_search_equipped("claude-opus-4-8", "auto")

    assert tools == [anthropic_web_search_tool("claude-opus-4-8")]
    assert tools[0]["type"] == "web_search_20260209"


def test_build_search_equipped_anthropic_haiku_uses_basic_server_tool(monkeypatch):
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda _model_id: "")

    _model, tools = build_search_equipped("claude-haiku-4-5", "auto")

    assert tools[0]["type"] == "web_search_20250305"


def test_openai_server_tool_shape_is_current():
    assert OPENAI_WEB_SEARCH_TOOL == {"type": "web_search"}


def test_deepseek_server_tool_shape_is_current():
    # DeepSeek runs `web_search` server-side on the Responses API and accepts the
    # same tool definition OpenAI does (verified live on both `web_search` and
    # `web_search_2025_08_26`). It is a separate constant because the two are
    # only incidentally equal: DeepSeek ignores search_context_size/user_location
    # and returns no url_citation annotations.
    assert DEEPSEEK_WEB_SEARCH_TOOL == {"type": "web_search"}


def test_build_search_equipped_deepseek_returns_native_server_tool(monkeypatch):
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda _model_id: "")

    model, tools = build_search_equipped("deepseek:deepseek-v4-flash", "auto")

    assert tools == [DEEPSEEK_WEB_SEARCH_TOOL]
    # Native search must not smuggle thinking back on: the search agent is built
    # non-reasoning here, and on Responses `effort` is the toggle.
    assert model.reasoning == {"effort": "none"}
    assert model.provider == "DeepSeek"
