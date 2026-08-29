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
from resume_agent.provider_registry import PROVIDER_SPECS

__all__ = [
    "DIRECT_API_BASE_URL_FIELDS",
    "ROUTE_MODE_FIELDS",
    "SUB2API_KEY_FIELDS",
    "EffectiveMode",
    "RouteConfigError",
    "direct_api_base_url",
    "effective_mode",
    "gateway_origin",
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
SUB2API_KEY_FIELDS = {spec.id: spec.subscription_key_field for spec in PROVIDER_SPECS}

DIRECT_API_BASE_URL_FIELDS = {
    spec.id: spec.direct_base_url_field
    for spec in PROVIDER_SPECS
    if spec.direct_base_url_field is not None
}

_DIRECT_API_BASE_URL_DEFAULTS = {
    spec.id: spec.default_direct_base_url
    for spec in PROVIDER_SPECS
    if spec.default_direct_base_url is not None
}

ROUTE_MODE_FIELDS = {spec.id: spec.route_mode_field for spec in PROVIDER_SPECS}


def _validated_base_url(raw_value: str, setting_name: str) -> str:
    """Return a validated HTTP(S) base URL without a trailing slash."""

    raw = (raw_value or "").strip().rstrip("/")
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
            f"{setting_name} must be an absolute http(s) URL with no "
            f"credentials, query, or fragment (got {raw_value!r})"
        )
    return raw


def _origin(settings: Settings) -> str:
    """The configured gateway origin, validated, without a trailing slash.

    Returns ``""`` when unset. A path prefix is allowed (sub2api behind a
    reverse proxy at ``/sub2api``); credentials, query, and fragment are not,
    because none of them survive being concatenated with an SDK's own path.
    """
    return _validated_base_url(settings.sub2api_base_url, "SUB2API_BASE_URL")


def direct_api_base_url(provider: str, settings: Settings) -> str | None:
    """The direct provider endpoint, kept separate from the gateway origin.

    OpenAI and Anthropic SDKs also read their base URLs from process environment
    variables. Returning an explicit value here prevents those implicit SDK
    defaults from crossing the selected route's key/endpoint boundary.
    """

    field = DIRECT_API_BASE_URL_FIELDS.get(provider)
    if field is None:
        return None
    configured = str(getattr(settings, field, "") or "")
    raw = configured or _DIRECT_API_BASE_URL_DEFAULTS[provider]
    return _validated_base_url(raw, field.upper())


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
        direct_api_base_url(provider, settings)
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
    if key:
        return "subscription"
    direct_api_base_url(provider, settings)
    return "api"


def gateway_origin(settings: Settings) -> str | None:
    """The validated gateway origin, or ``None`` when it is unset.

    Provider SDK path spelling deliberately lives in ``llm_runner``'s provider
    seam. The spend decision carries this single validated routing value next
    to its credential; the seam adapts it without re-reading configuration.
    """
    origin = _origin(settings)
    return origin or None
