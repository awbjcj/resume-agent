from __future__ import annotations

from types import SimpleNamespace

from resume_agent.config import Settings
from resume_agent.llm_runner import (
    build_model,
    build_search_equipped,
    model_access_available,
    refresh_agent_api_key,
)
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths

GATEWAY = "https://sub2api.example.com"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _context(tmp_path, settings: Settings) -> UserContext:
    return UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "abc123def456"),
        settings=settings,
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
        platform_provider_keys={},
        user_provider_keys={},
    )


def test_build_model_keeps_each_gateway_key_and_endpoint_together():
    settings = _settings(
        sub2api_base_url=GATEWAY,
        sub2api_anthropic_key="ant-sub",
        sub2api_openai_key="oai-sub",
        sub2api_gemini_key="gem-sub",
        sub2api_deepseek_key="deep-sub",
    )

    anthropic = build_model("claude-sonnet-5", settings=settings)
    openai = build_model("openai:gpt-5.6-terra", settings=settings)
    gemini = build_model("gemini:gemini-3.6-flash", settings=settings)
    deepseek = build_model("deepseek:deepseek-v4-flash", settings=settings)

    assert (anthropic.api_key, anthropic.client_params["base_url"]) == ("ant-sub", GATEWAY)
    assert (openai.api_key, openai.base_url) == ("oai-sub", f"{GATEWAY}/v1")
    assert (gemini.api_key, gemini.client_params["http_options"]["base_url"]) == ("gem-sub", GATEWAY)
    assert (deepseek.api_key, deepseek.base_url) == ("deep-sub", f"{GATEWAY}/v1")


def test_search_builder_uses_the_same_route_as_the_normal_builder():
    settings = _settings(sub2api_base_url=GATEWAY, sub2api_openai_key="oai-sub")

    model, tools = build_search_equipped(
        "openai:gpt-5.6-terra", mode="native", settings=settings
    )

    assert (model.api_key, model.base_url) == ("oai-sub", f"{GATEWAY}/v1")
    assert tools == [{"type": "web_search"}]


def test_api_pin_does_not_claim_subscription_only_access():
    settings = _settings(
        sub2api_base_url=GATEWAY,
        sub2api_anthropic_key="ant-sub",
        anthropic_route_mode="api",
    )

    assert model_access_available("claude-sonnet-5", settings=settings) is False


def test_subscription_route_is_available_without_any_direct_api_key():
    settings = _settings(
        sub2api_base_url=GATEWAY,
        sub2api_anthropic_key="ant-sub",
    )

    assert model_access_available("claude-sonnet-5", settings=settings) is True


def test_refresh_moves_a_reused_agent_key_and_endpoint_together(tmp_path):
    settings = _settings(sub2api_base_url=GATEWAY, sub2api_anthropic_key="ant-sub")
    model = SimpleNamespace(
        id="claude-sonnet-5",
        provider="Anthropic",
        api_key="old",
        client_params={"timeout": 30},
        client=object(),
        async_client=object(),
    )

    with use_context(_context(tmp_path, settings)):
        refresh_agent_api_key(SimpleNamespace(model=model), settings=settings)

    assert model.api_key == "ant-sub"
    assert model.client_params == {"timeout": 30, "base_url": GATEWAY}
    assert model.client is None
    assert model.async_client is None


def test_refresh_restores_deepseek_direct_default_after_gateway_is_disabled(tmp_path):
    gateway_settings = _settings(
        sub2api_base_url=GATEWAY,
        sub2api_deepseek_key="deep-sub",
    )
    direct_settings = _settings(
        deepseek_api_key="deep-direct",
        deepseek_route_mode="api",
    )
    model = build_model("deepseek:deepseek-v4-flash", settings=gateway_settings)
    context = _context(tmp_path, direct_settings)
    context.platform_provider_keys["deepseek"] = "deep-direct"

    with use_context(context):
        refresh_agent_api_key(SimpleNamespace(model=model), settings=direct_settings)

    assert model.api_key == "deep-direct"
    assert model.base_url == "https://api.deepseek.com"
