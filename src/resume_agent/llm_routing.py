"""Where each provider's LLM traffic goes: the subscription gateway, or its API.

A sub2api deployment fronts every provider at one origin, speaking each one's
**native wire format** at its own path -- ``/v1/messages`` for Anthropic,
``/v1/responses`` for OpenAI-compatible traffic, ``/v1beta/models/*`` for
Gemini. It also accepts the API key from whichever header that provider's SDK
already sends (``Authorization: Bearer``, ``x-api-key``, or
``x-goog-api-key``), so routing a call needs no custom headers and no request
rewriting -- only a different ``base_url`` and a different key.

That is the whole feature: one origin, one key per provider, and a per-provider
mode. This module owns the config vocabulary; ``tenancy.spend.SpendGate`` owns
the decision (so "which key?" keeps a single answer, per ADR-0009), and
``llm_runner.build_model`` owns the per-SDK plumbing.

**The fallback is configuration, not a branch.** A provider with no gateway key
-- DeepSeek and Gemini today -- resolves to its direct API key under the
default ``auto`` mode. Nothing in the call path special-cases a provider name.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from resume_agent.config import RouteMode, Settings

__all__ = [
    "ROUTE_MODE_FIELDS",
    "SUB2API_KEY_FIELDS",
    "EffectiveMode",
    "RouteConfigError",
    "effective_mode",
    "gateway_base_url",
    "route_mode",
    "subscription_configured",
    "subscription_key",
]

EffectiveMode = Literal["subscription", "api"]


class RouteConfigError(RuntimeError):
    """Routing config that cannot be honoured as written.

    Raised rather than degraded on purpose. Silently falling back to the direct
    provider API is the one failure mode this feature exists to prevent: it
    turns a typo in an env var into per-token billing that looks exactly like
    success, and the bill is the only signal.
    """


# provider -> Settings field. Both maps are the single enumeration of the
# routing vocabulary; the admin API derives its env-var names from them.
SUB2API_KEY_FIELDS: dict[str, str] = {
    "anthropic": "sub2api_anthropic_key",
    "openai": "sub2api_openai_key",
    "gemini": "sub2api_gemini_key",
    "deepseek": "sub2api_deepseek_key",
}

ROUTE_MODE_FIELDS: dict[str, str] = {
    "anthropic": "anthropic_route_mode",
    "openai": "openai_route_mode",
    "gemini": "gemini_route_mode",
    "deepseek": "deepseek_route_mode",
}

# What each provider's SDK expects to be handed, given a gateway origin. These
# differ because each SDK appends its own path to whatever base it is given:
# the Anthropic SDK appends "/v1/messages" and google-genai appends
# "/v1beta/models/...", so both want the bare origin, while the OpenAI SDK
# appends only "/responses" and therefore wants the "/v1" already on the end.
_BASE_URL_SUFFIX: dict[str, str] = {
    "anthropic": "",
    "openai": "/v1",
    "deepseek": "/v1",
    "gemini": "",
}


def _origin(settings: Settings) -> str:
    """The configured gateway origin, validated, without a trailing slash.

    Returns ``""`` when unset. A path prefix is allowed (sub2api behind a
    reverse proxy at ``/sub2api``); credentials, query, and fragment are not,
    because none of them survive being concatenated with an SDK's own path.
    """
    raw = (settings.sub2api_base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RouteConfigError(
            "SUB2API_BASE_URL must be an absolute http(s) URL with no "
            f"credentials, query, or fragment (got {settings.sub2api_base_url!r})"
        )
    return raw


def subscription_key(provider: str, settings: Settings) -> str:
    """The gateway key configured for ``provider``, or ``""``."""
    field = SUB2API_KEY_FIELDS.get(provider)
    return str(getattr(settings, field, "") or "") if field else ""


def route_mode(provider: str, settings: Settings) -> RouteMode:
    """The configured (unresolved) mode for ``provider``."""
    field = ROUTE_MODE_FIELDS.get(provider)
    return getattr(settings, field, "auto") if field else "auto"


def subscription_configured(provider: str, settings: Settings) -> bool:
    """Whether ``provider`` has everything it needs to route to the gateway."""
    return bool(_origin(settings)) and bool(subscription_key(provider, settings))


def effective_mode(provider: str, settings: Settings) -> EffectiveMode:
    """Resolve ``auto`` against what is actually configured.

    ``subscription`` and ``api`` are an admin's explicit instruction and are
    honoured literally -- ``subscription`` raises when it cannot be satisfied
    rather than quietly reverting to the metered API.

    ``auto`` degrades to ``api`` when the provider has no gateway key, which is
    what makes DeepSeek and Gemini work today with no code path of their own.
    It still raises when a key is configured but the origin is missing, because
    that combination has no honest reading: someone set up a subscription
    credential and gave it nowhere to go.
    """
    mode = route_mode(provider, settings)
    if mode == "api":
        return "api"

    origin = _origin(settings)
    key = subscription_key(provider, settings)

    if mode == "subscription":
        if not origin:
            raise RouteConfigError(
                f"{provider} is pinned to subscription mode but SUB2API_BASE_URL is unset"
            )
        if not key:
            raise RouteConfigError(
                f"{provider} is pinned to subscription mode but "
                f"{SUB2API_KEY_FIELDS[provider].upper()} is unset"
            )
        return "subscription"

    if key and not origin:
        raise RouteConfigError(
            f"{SUB2API_KEY_FIELDS[provider].upper()} is set but SUB2API_BASE_URL "
            "is unset, so there is nowhere to send the call"
        )
    return "subscription" if key else "api"


def gateway_base_url(provider: str, settings: Settings) -> str | None:
    """The ``base_url`` ``provider``'s SDK needs to reach the gateway.

    ``None`` when the provider is not on the gateway, which every caller reads
    as "leave the SDK's own default alone".
    """
    origin = _origin(settings)
    if not origin:
        return None
    return f"{origin}{_BASE_URL_SUFFIX.get(provider, '')}"
