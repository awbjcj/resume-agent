import pytest

from resume_agent.llm_runner import (
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
        ("deepseek:deepseek-chat", "tool"),
    ],
)
def test_plan_auto_selects_provider_strategy(model_id, strategy):
    assert plan_search(model_id, "auto").strategy == strategy


def test_plan_tool_mode_forces_tool_for_anthropic():
    assert plan_search("claude-opus-4-8", "tool").strategy == "tool"


def test_plan_native_mode_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="no native web search"):
        plan_search("deepseek:deepseek-chat", "native")


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
