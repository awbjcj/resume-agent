from typing import Any, Protocol

from resume_agent.config import get_settings


class Runner(Protocol):
    """Minimal callable surface the pipeline expects from an LLM agent."""

    def run(self, prompt: str) -> Any: ...


class AgentRunner:
    """Adapter that narrows third-party agent APIs to ``run(prompt: str)``."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def run(self, prompt: str) -> Any:
        return self._agent.run(prompt)


# Providers selectable via a ``provider:model`` prefix on any model id. A bare id
# (no recognised prefix) stays Anthropic, so existing config keeps working.
PROVIDERS = ("anthropic", "openai", "gemini", "deepseek")


def split_provider(model_id: str) -> tuple[str, str]:
    """Split ``"provider:model"`` into ``(provider, model)``.

    A bare id, or one whose prefix is not a known provider (e.g. a Workday-style
    ``"tenant:site"`` that is never a model id), defaults to Anthropic so legacy
    Claude ids pass through unchanged.
    """
    prefix, sep, rest = model_id.partition(":")
    if sep and prefix in PROVIDERS:
        return prefix, rest
    return "anthropic", model_id


def resolve_api_key(model_id: str) -> str:
    """Return the configured key for ``model_id``'s provider, or ``""`` if unset."""
    provider, _ = split_provider(model_id)
    s = get_settings()
    return {
        "anthropic": s.anthropic_api_key,
        "openai": s.openai_api_key,
        "gemini": s.gemini_api_key,
        "deepseek": s.deepseek_api_key,
    }.get(provider, "")


def build_model(model_id: str, api_key: str | None = None) -> Any:
    """Construct the agno model for a (possibly provider-prefixed) ``model_id``.

    Provider SDK modules are imported lazily, per branch: a Claude-only run never
    imports ``openai`` or ``google-genai``, and a missing optional SDK fails only
    when that provider is actually selected.
    """
    provider, model = split_provider(model_id)
    key = api_key or resolve_api_key(model_id) or None
    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model, api_key=key)
    if provider == "gemini":
        from agno.models.google import Gemini

        return Gemini(id=model, api_key=key)
    if provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(id=model, api_key=key)
    from agno.models.anthropic import Claude

    return Claude(id=model, api_key=key)
