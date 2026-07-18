import asyncio
import logging
import time
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any, Literal, Protocol, TypeVar, cast

from resume_agent.config import get_settings

logger = logging.getLogger(__name__)


class Runner(Protocol):
    """Minimal surface the pipeline expects from an LLM agent."""

    def run(self, prompt: str) -> Any: ...

    async def arun(self, prompt: str) -> Any: ...


class _ModelWithAsyncClient(Protocol):
    async_client: Any | None


# Failures worth retrying: rate limits, overload, timeouts, dropped connections.
# Matched by status code and class name so no provider SDK is imported here
# (the same lazy-import rule build_model follows).
_TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_TRANSIENT_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "InternalServerError",
    "OverloadedError",
    "PoolTimeout",
    "RateLimitError",
    "ReadTimeout",
    "RemoteProtocolError",
    "ServiceUnavailableError",
    "TimeoutException",
    "WriteTimeout",
}


def is_transient(exc: BaseException) -> bool:
    """Whether an LLM-call failure is worth retrying.

    Auth, schema, and parse failures are deterministic — retrying them burns
    llm_retries x tokens for the same answer — so anything unrecognized is
    treated as permanent.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUS
    return any(klass.__name__ in _TRANSIENT_NAMES for klass in type(exc).__mro__)


class AgentRunner:
    """Adapter that narrows third-party agent APIs to ``run`` / ``arun``."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def run(self, prompt: str) -> Any:
        settings = get_settings()
        for attempt in range(settings.llm_retries + 1):
            try:
                response = self._agent.run(prompt)
                from resume_agent.tenancy.usage import record_call

                record_call(self._agent, response)
                return response
            except Exception as exc:
                if attempt >= settings.llm_retries or not is_transient(exc):
                    raise
                time.sleep(settings.llm_retry_delay * (2**attempt))
        raise AssertionError("unreachable")

    async def arun(self, prompt: str) -> Any:
        settings = get_settings()
        for attempt in range(settings.llm_retries + 1):
            try:
                response = await self._agent.arun(prompt)
                from resume_agent.tenancy.usage import record_call

                record_call(self._agent, response)
                return response
            except Exception as exc:
                if attempt >= settings.llm_retries or not is_transient(exc):
                    raise
                await asyncio.sleep(settings.llm_retry_delay * (2**attempt))
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        """Close and detach the SDK's cached async client on its active loop."""
        model = cast(_ModelWithAsyncClient | None, getattr(self._agent, "model", None))
        if model is None:
            return
        client = getattr(model, "async_client", None)
        if client is None:
            return
        try:
            close = getattr(client, "close", None) or getattr(client, "aclose", None)
            if close is not None:
                result = close()
                if isawaitable(result):
                    await result
        finally:
            if getattr(model, "async_client", None) is client:
                model.async_client = None


async def aclose_runner(runner: Any) -> None:
    """Close a runner when it exposes async lifecycle ownership."""
    close = getattr(runner, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result


_T = TypeVar("_T")


async def run_with_cleanup(operation: Awaitable[_T], *runners: Any) -> _T:
    """Await an operation, then close its unique runners before loop shutdown."""
    try:
        return await operation
    finally:
        seen: set[int] = set()
        for runner in runners:
            identity = id(runner)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                await aclose_runner(runner)
            except Exception:
                logger.warning("Failed to close LLM runner", exc_info=True)


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


def build_model(
    model_id: str,
    api_key: str | None = None,
    *,
    cache_system_prompt: bool = False,
) -> Any:
    """Construct the agno model for a (possibly provider-prefixed) ``model_id``.

    Provider SDK modules are imported lazily, per branch: a Claude-only run never
    imports ``openai`` or ``google-genai``, and a missing optional SDK fails only
    when that provider is actually selected. ``cache_system_prompt`` is forwarded
    only to Anthropic; other providers ignore it.
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

    return Claude(
        id=model,
        api_key=key,
        cache_system_prompt=cache_system_prompt,
    )


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
    """agno per-agent retry config, spread into every ``Agent(...)`` we build.

    Retries live in AgentRunner behind the is_transient predicate; agno's own
    bare-``Exception`` retry is disabled so a deterministic failure (auth,
    schema, parse) surfaces after one call instead of 1 + llm_retries.
    """
    return {"retries": 0}


def tool_kwargs() -> dict[str, Any]:
    """Bound tool calls across one complete agno agent run."""
    return {"tool_call_limit": 15}


_TRANSCRIBE_PROVIDERS = ("gemini", "openai")
_TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim. Return only the spoken words as plain text, "
    "with normal punctuation and no commentary."
)
_OPENAI_AUDIO_NAMES = {
    "audio/webm": "audio.webm",
    "audio/ogg": "audio.ogg",
    "audio/mpeg": "audio.mp3",
    "audio/mp4": "audio.mp4",
    "audio/wav": "audio.wav",
    "audio/x-wav": "audio.wav",
}


def transcription_available() -> bool:
    """Whether the configured transcribe model's provider has audio support and a key."""
    model_id = get_settings().transcribe_model
    provider, _ = split_provider(model_id)
    return provider in _TRANSCRIBE_PROVIDERS and bool(resolve_api_key(model_id))


def transcribe(audio: bytes, mime_type: str, *, model_id: str | None = None) -> str:
    """Transcribe audio via the configured provider. The only audio-SDK seam.

    Claude models cannot accept audio; Gemini uses inline-audio generation and
    OpenAI its transcription API. SDK imports are lazy, per branch.
    """
    resolved = model_id or get_settings().transcribe_model
    provider, model = split_provider(resolved)
    if provider not in _TRANSCRIBE_PROVIDERS:
        raise ValueError(f"provider {provider!r} does not support audio transcription")
    key = resolve_api_key(resolved)
    if not key:
        raise ValueError(f"no API key configured for transcription provider {provider!r}")
    if provider == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=audio, mime_type=mime_type),
                _TRANSCRIBE_PROMPT,
            ],
        )
        return (response.text or "").strip()
    import io

    from openai import OpenAI

    client = OpenAI(api_key=key)
    buffer = io.BytesIO(audio)
    buffer.name = _OPENAI_AUDIO_NAMES.get(mime_type, "audio.webm")
    result = client.audio.transcriptions.create(model=model, file=buffer)
    return result.text.strip()
