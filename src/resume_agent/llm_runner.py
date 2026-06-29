import asyncio
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal, Protocol

from resume_agent.config import get_settings


class Runner(Protocol):
    """Minimal surface the pipeline expects from an LLM agent."""

    def run(self, prompt: str) -> Any: ...

    async def arun(self, prompt: str) -> Any: ...


class AgentRunner:
    """Adapter that narrows third-party agent APIs to ``run`` / ``arun``."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def run(self, prompt: str) -> Any:
        return self._agent.run(prompt)

    async def arun(self, prompt: str) -> Any:
        return await self._agent.arun(prompt)


# Providers selectable via a ``provider:model`` prefix on any model id. A bare id
# (no recognised prefix) stays Anthropic, so existing config keeps working.
PROVIDERS = ("anthropic", "openai", "gemini", "deepseek")

ANTHROPIC_WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}
OPENAI_WEB_SEARCH_TOOL = {"type": "web_search_preview"}

SearchMode = Literal["auto", "native", "tool", "off"]
SearchStrategy = Literal[
    "none",
    "tool",
    "native_anthropic",
    "native_openai",
    "native_gemini",
]
_NATIVE_SEARCH_STRATEGIES: dict[str, SearchStrategy] = {
    "anthropic": "native_anthropic",
    "openai": "native_openai",
    "gemini": "native_gemini",
}


@dataclass(frozen=True)
class SearchPlan:
    provider: str
    strategy: SearchStrategy


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


def plan_search(model_id: str, mode: SearchMode) -> SearchPlan:
    """Choose a provider-native or tool-backed search strategy without I/O."""
    provider, _model = split_provider(model_id)
    if mode == "off":
        return SearchPlan(provider, "none")
    if mode == "tool":
        return SearchPlan(provider, "tool")

    native_strategy = _NATIVE_SEARCH_STRATEGIES.get(provider)
    if mode == "native" and native_strategy is None:
        raise ValueError(
            f"search_mode=native but provider {provider!r} has no native web search"
        )
    return SearchPlan(provider, native_strategy or "tool")


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


def use_json_mode_for(model: Any) -> bool:
    """Whether an ``output_schema`` agent over ``model`` must use JSON mode.

    Providers without native/json_schema structured outputs (e.g. DeepSeek)
    honour an ``output_schema`` only via ``response_format`` JSON mode; without
    it they intermittently return prose that agno cannot parse, falling back to
    the raw ``str``. Providers that *do* support it — OpenAI, Anthropic — keep
    their stricter native structured outputs (``use_json_mode=False``). The flag
    is read off the agno model itself, so this stays correct as providers gain
    or lose native support.
    """
    return not getattr(model, "supports_native_structured_outputs", False)


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


def build_search_equipped(
    model_id: str,
    mode: SearchMode | None = None,
) -> tuple[Any, list[Any]]:
    """Build a model and its search tools for advisor research."""
    settings = get_settings()
    plan = plan_search(model_id, mode or settings.search_mode)
    if plan.strategy == "none":
        raise ValueError("advisor web search is disabled by search_mode=off")
    _provider, model_name = split_provider(model_id)
    api_key = resolve_api_key(model_id) or None

    if plan.strategy == "native_openai":
        from agno.models.openai.responses import OpenAIResponses

        return OpenAIResponses(id=model_name, api_key=api_key), [OPENAI_WEB_SEARCH_TOOL]
    if plan.strategy == "native_gemini":
        from agno.models.google import Gemini

        return Gemini(id=model_name, api_key=api_key, search=True), []

    model = build_model(model_id, api_key=api_key)
    if plan.strategy == "native_anthropic":
        return model, [ANTHROPIC_WEB_SEARCH_TOOL]
    if plan.strategy == "tool":
        from agno.tools.duckduckgo import DuckDuckGoTools

        return model, [DuckDuckGoTools()]
    raise AssertionError(f"unhandled search strategy: {plan.strategy}")


def _observe(callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    try:
        callback()
    except Exception:
        pass


async def acall(
    agent: Runner,
    prompt: str,
    *,
    sem: asyncio.Semaphore,
    on_acquire: Callable[[], None] | None = None,
    on_release: Callable[[], None] | None = None,
) -> Any:
    """Run one agent call, holding a semaphore permit only for its duration."""
    async with sem:
        _observe(on_acquire)
        try:
            return await agent.arun(prompt)
        finally:
            _observe(on_release)


def retry_kwargs() -> dict[str, Any]:
    """agno per-agent retry config, spread into every ``Agent(...)`` we build."""
    s = get_settings()
    return {
        "retries": s.llm_retries,
        "delay_between_retries": s.llm_retry_delay,
        "exponential_backoff": True,
    }
