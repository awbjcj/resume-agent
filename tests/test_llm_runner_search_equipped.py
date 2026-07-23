from agno.models.google.gemini_interactions import GeminiInteractions

from resume_agent.llm_runner import build_search_equipped


def test_native_search_forwards_safe_provider_options():
    claude, claude_tools = build_search_equipped(
        "claude-sonnet-5",
        mode="native",
        reasoning=True,
        cache_system_prompt=True,
    )
    assert claude.thinking == {"type": "adaptive"}
    assert claude.cache_system_prompt is True
    assert claude_tools[0]["name"] == "web_search"

    openai, _ = build_search_equipped(
        "openai:gpt-5.6", mode="native", reasoning=True
    )
    assert openai.reasoning_effort == "high"
    assert openai.store is False

    gemini, gemini_tools = build_search_equipped(
        "gemini:gemini-3.5-flash", mode="native", reasoning=True
    )
    assert isinstance(gemini, GeminiInteractions)
    assert gemini.thinking_level == "high"
    assert gemini.search is True
    assert gemini.store is False
    assert gemini_tools == []


def test_search_builder_gates_incapable_reasoning_request():
    model, _ = build_search_equipped(
        "openai:gpt-4o", mode="native", reasoning=True
    )
    assert model.reasoning_effort is None
