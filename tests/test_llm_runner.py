import pytest

from resume_agent.llm_runner import build_model, resolve_api_key, split_provider


def test_split_provider_bare_id_defaults_anthropic():
    assert split_provider("claude-opus-4-8") == ("anthropic", "claude-opus-4-8")


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("openai:gpt-5.4-mini", ("openai", "gpt-5.4-mini")),
        ("gemini:gemini-2.0-flash", ("gemini", "gemini-2.0-flash")),
        ("deepseek:deepseek-chat", ("deepseek", "deepseek-chat")),
    ],
)
def test_split_provider_parses_known_prefixes(model_id, expected):
    assert split_provider(model_id) == expected


def test_split_provider_unknown_prefix_stays_anthropic():
    # A Workday-style "tenant:site" is never a model id; it must not be mistaken
    # for a provider, so it passes through whole as an Anthropic id.
    assert split_provider("tenant:site") == ("anthropic", "tenant:site")


def test_resolve_api_key_reads_provider_specific_setting(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk")
    from resume_agent.config import get_settings

    get_settings.cache_clear()
    assert resolve_api_key("claude-opus-4-8") == "ak"
    assert resolve_api_key("openai:gpt-5.4-mini") == "ok"
    assert resolve_api_key("gemini:gemini-2.0-flash") == "gk"
    assert resolve_api_key("deepseek:deepseek-chat") == "dk"
    get_settings.cache_clear()


def test_build_model_anthropic_branch():
    from agno.models.anthropic import Claude

    model = build_model("claude-opus-4-8", api_key="sk-test")
    assert isinstance(model, Claude)
    assert model.id == "claude-opus-4-8"
    assert model.api_key == "sk-test"


def test_build_model_openai_branch():
    OpenAIChat = pytest.importorskip("agno.models.openai").OpenAIChat
    model = build_model("openai:gpt-5.4-mini", api_key="sk-test")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-5.4-mini"
    assert model.api_key == "sk-test"


def test_build_model_gemini_branch():
    Gemini = pytest.importorskip("agno.models.google").Gemini
    model = build_model("gemini:gemini-2.0-flash", api_key="sk-test")
    assert isinstance(model, Gemini)
    assert model.id == "gemini-2.0-flash"


def test_build_model_deepseek_branch():
    DeepSeek = pytest.importorskip("agno.models.deepseek").DeepSeek
    model = build_model("deepseek:deepseek-chat", api_key="sk-test")
    assert isinstance(model, DeepSeek)
    assert model.id == "deepseek-chat"


def test_agent_runner_arun_delegates():
    import asyncio

    from resume_agent.llm_runner import AgentRunner

    class _AsyncAgent:
        async def arun(self, prompt):
            return f"got {prompt}"

    out = asyncio.run(AgentRunner(_AsyncAgent()).arun("hi"))
    assert out == "got hi"


def test_acall_respects_semaphore_limit():
    import asyncio

    from resume_agent.concurrency import gather_isolated
    from resume_agent.llm_runner import acall

    state = {"now": 0, "max": 0}

    class _Result:
        def __init__(self, content):
            self.content = content

    class _Agent:
        def run(self, prompt):
            return _Result(prompt)

        async def arun(self, prompt):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.02)
            state["now"] -= 1
            return _Result(prompt)

    async def go():
        sem = asyncio.Semaphore(2)
        return await gather_isolated(
            range(6), lambda i: acall(_Agent(), str(i), sem=sem)
        )

    results = asyncio.run(go())
    assert state["max"] <= 2
    assert all(r.ok for r in results)


def test_retry_kwargs_reads_settings(monkeypatch):
    monkeypatch.setenv("LLM_RETRIES", "5")
    monkeypatch.setenv("LLM_RETRY_DELAY", "3")
    from resume_agent.config import get_settings
    from resume_agent.llm_runner import retry_kwargs

    get_settings.cache_clear()
    try:
        assert retry_kwargs() == {
            "retries": 5,
            "delay_between_retries": 3,
            "exponential_backoff": True,
        }
    finally:
        get_settings.cache_clear()
