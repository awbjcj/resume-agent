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

    openai, openai_tools = build_search_equipped(
        "openai:gpt-5.6-terra", mode="native", reasoning=True
    )
    assert openai.reasoning == {"effort": "high"}
    assert openai.store is False
    assert openai_tools == [{"type": "web_search"}]

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
    assert model.reasoning is None


def test_native_gemini_search_bounds_thinking_when_not_reasoning():
    # Gemini treats an unset thinking config as "provider decides" (unbounded
    # automatic budget), so the non-reasoning research agent has to bound it --
    # the same rule build_model follows. Only reasoning=True was covered before.
    gemini, _ = build_search_equipped(
        "gemini:gemini-3.5-flash", mode="native", reasoning=False
    )
    assert isinstance(gemini, GeminiInteractions)
    assert gemini.thinking_level == "low"


def test_native_openai_search_reuses_the_shared_builder():
    from resume_agent.llm_runner import build_model

    searched, tools = build_search_equipped(
        "openai:gpt-5.5-pro", mode="native", reasoning=True
    )
    direct = build_model("openai:gpt-5.5-pro", api_key=None, reasoning=True)

    assert type(searched) is type(direct)
    assert searched.id == direct.id
    assert searched.reasoning == direct.reasoning
    assert searched.max_output_tokens == direct.max_output_tokens
    assert searched.store == direct.store
    assert tools == [{"type": "web_search"}]
