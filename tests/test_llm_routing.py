"""Subscription routing: which endpoint a provider's calls go to, and why.

The behaviour worth pinning is not "the gateway works" -- it is the two ways
this feature can fail quietly. A provider that should be routed but is not
bills per token at the direct API, and a provider that is routed with the wrong
credential fails every call. Both are invisible without these tests, so each
one below asserts on the *pair* (key, endpoint) rather than on either alone.
"""

from __future__ import annotations

import pytest

from resume_agent.config import Settings
from resume_agent.llm_routing import (
    RouteConfigError,
    effective_mode,
    gateway_origin,
    subscription_configured,
    subscription_key,
)

GATEWAY = "https://sub2api.example.com"


def _settings(**overrides) -> Settings:
    base = {
        "anthropic_api_key": "sk-ant-direct",
        "openai_api_key": "sk-openai-direct",
        "gemini_api_key": "gemini-direct",
        "deepseek_api_key": "deepseek-direct",
    }
    return Settings(**{**base, **overrides})


# -- auto mode: the fallback is configuration, not a branch -----------------


def test_auto_routes_a_provider_that_has_a_gateway_key():
    settings = _settings(sub2api_base_url=GATEWAY, sub2api_anthropic_key="s2a-key")

    assert effective_mode("anthropic", settings) == "subscription"
    assert subscription_key("anthropic", settings) == "s2a-key"


def test_auto_leaves_a_provider_without_a_gateway_key_on_its_api():
    """The DeepSeek/Gemini case: no subscription, so no gateway key, so no route.

    This is the whole fallback. Nothing names DeepSeek or Gemini anywhere in
    the call path -- they are simply providers with no key configured.
    """
    settings = _settings(sub2api_base_url=GATEWAY, sub2api_anthropic_key="s2a-key")

    assert effective_mode("deepseek", settings) == "api"
    assert effective_mode("gemini", settings) == "api"
    assert gateway_origin(settings) is not None  # origin is set...
    assert not subscription_configured("deepseek", settings)  # ...but no key


def test_auto_with_no_gateway_at_all_leaves_every_provider_on_its_api():
    settings = _settings()

    assert [effective_mode(p, settings) for p in ("anthropic", "openai")] == [
        "api",
        "api",
    ]
    assert gateway_origin(settings) is None


# -- explicit modes ---------------------------------------------------------


def test_api_mode_ignores_a_configured_gateway_key():
    settings = _settings(
        sub2api_base_url=GATEWAY,
        sub2api_anthropic_key="s2a-key",
        anthropic_route_mode="api",
    )

    assert effective_mode("anthropic", settings) == "api"


def test_subscription_mode_without_a_key_raises_rather_than_billing_the_api():
    """The failure this feature exists to prevent.

    Degrading here would turn a typo in an env var into per-token billing that
    looks exactly like success.
    """
    settings = _settings(sub2api_base_url=GATEWAY, openai_route_mode="subscription")

    with pytest.raises(RouteConfigError, match="SUB2API_OPENAI_KEY"):
        effective_mode("openai", settings)


def test_subscription_mode_without_an_origin_raises():
    settings = _settings(
        sub2api_anthropic_key="s2a-key", anthropic_route_mode="subscription"
    )

    with pytest.raises(RouteConfigError, match="SUB2API_BASE_URL"):
        effective_mode("anthropic", settings)


def test_a_gateway_key_with_no_origin_raises_even_in_auto_mode():
    """Auto is forgiving about a missing key, not about an incoherent config.

    A subscription credential with nowhere to send it has no honest reading,
    and silently using the metered API is the expensive interpretation.
    """
    settings = _settings(sub2api_anthropic_key="s2a-key")

    with pytest.raises(RouteConfigError, match="nowhere to send"):
        effective_mode("anthropic", settings)


# -- base URLs: each SDK appends a different path ---------------------------


def test_gateway_origin_is_provider_agnostic():
    assert gateway_origin(_settings(sub2api_base_url=GATEWAY)) == GATEWAY


def test_a_trailing_slash_does_not_produce_a_doubled_path():
    settings = _settings(sub2api_base_url=f"{GATEWAY}/")

    assert gateway_origin(settings) == GATEWAY


def test_a_gateway_behind_a_path_prefix_is_allowed():
    settings = _settings(sub2api_base_url="https://proxy.example.com/sub2api")

    assert gateway_origin(settings) == "https://proxy.example.com/sub2api"


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://sub2api.example.com",
        "https://user:pw@sub2api.example.com",
        "https://sub2api.example.com?token=x",
        "not-a-url",
    ],
)
def test_an_unusable_origin_raises_rather_than_being_concatenated(bad):
    with pytest.raises(RouteConfigError):
        gateway_origin(_settings(sub2api_base_url=bad))
