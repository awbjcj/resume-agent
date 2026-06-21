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
