import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from inspect import isawaitable
from typing import Any, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel

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


_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

# Enough head to identify the shape, enough tail to see where it stopped.
_PREVIEW_HEAD = 600
_PREVIEW_TAIL = 400


class UnparsedAgentOutput(TypeError):
    """An agent returned raw content instead of the schema it was asked for.

    agno leaves ``RunOutput.content`` as the raw ``str`` whenever it cannot
    coerce a response into ``output_schema``, so this is the only signal that a
    structured call failed. It subclasses ``TypeError`` because that is what
    every call site raised before, and it carries the diagnostics that separate
    a truncated response from a refusal or a rejected schema -- none of which
    are recoverable from the type name alone, and none of which agno's Gemini
    adapter reports (it discards ``finish_reason`` unless a function call was
    malformed).
    """


def _preview(text: str) -> str:
    """Head + tail of ``text``.

    The tail is the diagnostic: a response cut off by an output-token ceiling
    ends mid-JSON, which a head-only preview would hide entirely.
    """
    if len(text) <= _PREVIEW_HEAD + _PREVIEW_TAIL:
        return text
    elided = len(text) - _PREVIEW_HEAD - _PREVIEW_TAIL
    return (
        f"{text[:_PREVIEW_HEAD]}"
        f" ... <{elided} chars elided> ... "
        f"{text[-_PREVIEW_TAIL:]}"
    )


def _describe_unparsed(result: Any, content: Any, schema: type, source: str) -> str:
    """Build the failure message, reading every field defensively.

    ``RunOutput``'s shape drifts between agno versions, so a missing attribute
    must degrade the report rather than raise over the failure it describes.
    """
    fields = [
        (
            f"Expected {schema.__name__} from {source} agent, "
            f"got {type(content).__name__}"
        )
    ]
    provider = getattr(result, "model_provider", None)
    model = getattr(result, "model", None)
    if provider or model:
        fields.append(f"model={provider or '?'}:{model or '?'}")
    status = getattr(result, "status", None)
    if status is not None:
        fields.append(f"status={getattr(status, 'value', status)}")
    metrics = getattr(result, "metrics", None)
    if metrics is not None:
        # reasoning tokens are how we tell whether provider-side thinking was
        # actually disabled, and output tokens whether a ceiling was reached.
        fields.append(
            f"tokens: in={getattr(metrics, 'input_tokens', 0)} "
            f"out={getattr(metrics, 'output_tokens', 0)} "
            f"reasoning={getattr(metrics, 'reasoning_tokens', 0)}"
        )
    if isinstance(content, str):
        fields.append(f"chars={len(content)}")
        return "; ".join(fields) + f"\ncontent: {_preview(content)}"
    return "; ".join(fields)


def expect_schema(result: Any, schema: type[_SchemaT], *, source: str) -> _SchemaT:
    """Return ``result.content`` as ``schema``, or raise saying why it is not.

    The single seam every structured-output call site should use, so a parse
    failure is diagnosable from the error alone instead of needing a redeploy.
    """
    content = getattr(result, "content", None)
    if isinstance(content, schema):
        return content
    raise UnparsedAgentOutput(_describe_unparsed(result, content, schema, source))


# Providers selectable via a ``provider:model`` prefix on any model id. A bare id
# (no recognised prefix) stays Anthropic, so existing config keeps working.
PROVIDERS = ("anthropic", "openai", "gemini", "deepseek")

PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
}


@dataclass(frozen=True)
class ModelCatalogEntry:
    """One selectable model id in the cheap/mid/premium tier pickers."""

    id: str
    label: str


# Curated model choices per provider for the tier pickers, so a UI can offer a
# closed dropdown instead of free text a user could mistype. Ids follow the
# same ``provider:model`` convention as everywhere else in this module — bare
# ids are Anthropic. Update this list as providers ship new models.
MODEL_CATALOG: dict[str, list[ModelCatalogEntry]] = {
    "anthropic": [
        ModelCatalogEntry("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        ModelCatalogEntry("claude-sonnet-5", "Claude Sonnet 5"),
        ModelCatalogEntry("claude-opus-4-8", "Claude Opus 4.8"),
    ],
    "openai": [
        ModelCatalogEntry("openai:gpt-5.6-luna", "GPT-5.6 Luna"),
        ModelCatalogEntry("openai:gpt-5.6-terra", "GPT-5.6 Terra"),
        ModelCatalogEntry("openai:gpt-5.6-sol", "GPT-5.6 Sol"),
        ModelCatalogEntry("openai:gpt-5.5-pro", "GPT-5.5 Pro"),
        ModelCatalogEntry("openai:gpt-5.5", "GPT-5.5"),
        ModelCatalogEntry("openai:gpt-5.4-mini", "GPT-5.4 Mini"),
    ],
    "gemini": [
        ModelCatalogEntry("gemini:gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"),
        ModelCatalogEntry("gemini:gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
        ModelCatalogEntry("gemini:gemini-3.6-flash", "Gemini 3.6 Flash"),
        ModelCatalogEntry("gemini:gemini-3.5-flash", "Gemini 3.5 Flash"),
        ModelCatalogEntry("gemini:gemini-3.1-pro-preview", "Gemini 3.1 Pro (Preview)"),
    ],
    "deepseek": [
        ModelCatalogEntry("deepseek:deepseek-v4-flash", "DeepSeek V4 Flash"),
        ModelCatalogEntry("deepseek:deepseek-v4-pro", "DeepSeek V4 Pro"),
    ],
}

OPENAI_WEB_SEARCH_TOOL = {"type": "web_search"}


def anthropic_web_search_tool(model_id: str) -> dict[str, Any]:
    """Pick the Anthropic web-search tool variant for a (possibly bare) Claude model id.

    ``web_search_20260209`` (dynamic filtering) requires Opus 4.6+ or Sonnet 4.6+;
    Haiku models need the basic ``web_search_20250305`` type. Mirrors the
    "haiku" check `provider_capabilities` already uses for reasoning support.
    """
    _provider, model = split_provider(model_id)
    tool_type = (
        "web_search_20250305" if "haiku" in model.casefold() else "web_search_20260209"
    )
    return {"type": tool_type, "name": "web_search", "max_uses": 5}


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


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider-native features safe to request for a resolved model."""

    supports_reasoning: bool
    supports_native_citations: bool
    supports_prompt_cache: bool


_NO_PROVIDER_CAPABILITIES = ProviderCapabilities(False, False, False)


def provider_capabilities(model_id: str) -> ProviderCapabilities:
    """Return conservative capabilities without importing a provider SDK."""
    if not model_id:
        return _NO_PROVIDER_CAPABILITIES
    prefix, separator, _rest = model_id.partition(":")
    if separator and prefix not in PROVIDERS:
        return _NO_PROVIDER_CAPABILITIES

    provider, model = split_provider(model_id)
    folded = model.casefold()
    if provider == "anthropic" and folded.startswith("claude-"):
        return ProviderCapabilities("haiku" not in folded, True, True)
    if provider == "openai" and folded.startswith(("gpt-", "o1", "o3", "o4")):
        return ProviderCapabilities(
            folded.startswith(("gpt-5", "o1", "o3", "o4")), True, True
        )
    if provider == "gemini" and folded.startswith("gemini-"):
        return ProviderCapabilities(
            folded.startswith(("gemini-3", "gemini-2.5")), True, True
        )
    if provider == "deepseek" and folded.startswith("deepseek-"):
        reasoning = "reasoner" in folded or folded.startswith("deepseek-v4")
        return ProviderCapabilities(reasoning, False, True)
    return _NO_PROVIDER_CAPABILITIES


def supports_native_search(model_id: str) -> bool:
    """Whether ``model_id``'s provider gets provider-native web search.

    Providers outside this set (DeepSeek) still get search under
    ``search_mode=auto`` — ``plan_search`` falls back to the DuckDuckGo tool —
    just not the higher-quality native variant.
    """
    provider, _model = split_provider(model_id)
    return provider in _NATIVE_SEARCH_STRATEGIES


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


def missing_model_keys(settings) -> list[str]:
    """Configured mid/cheap tier models whose provider key is absent.

    Returns ``"tier (model)"`` labels for surfaces that gate LLM features on
    key presence (coach router, interview router, coach CLI).
    """
    configured = (("mid", settings.mid_model), ("cheap", settings.cheap_model))
    return [
        f"{tier} ({model})" for tier, model in configured if not resolve_api_key(model)
    ]


_ANTHROPIC_MAX_OPTIONAL_PROPERTIES = 24
_ANTHROPIC_MAX_UNION_PROPERTIES = 16


def _pydantic_json_schema(output_schema: Any) -> dict[str, Any] | None:
    """Return a detached JSON schema for a Pydantic output model, when possible."""
    if isinstance(output_schema, dict):
        return deepcopy(output_schema)
    if isinstance(output_schema, type) and issubclass(output_schema, BaseModel):
        return output_schema.model_json_schema()
    return None


def _walk_json_schema(value: Any):
    """Yield every mapping node in a JSON-compatible schema."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_schema(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_schema(child)


def _anthropic_schema_exceeds_limits(output_schema: Any) -> bool:
    """Whether Claude's native grammar compiler will reject ``output_schema``."""
    schema = _pydantic_json_schema(output_schema)
    if schema is None:
        return False

    optional_properties = 0
    union_properties = 0
    for node in _walk_json_schema(schema):
        properties = node.get("properties")
        if isinstance(properties, dict):
            required = set(node.get("required", ()))
            optional_properties += len(set(properties) - required)
        if any(
            isinstance(node.get(keyword), list) and len(node[keyword]) > 1
            for keyword in ("anyOf", "oneOf")
        ):
            union_properties += 1
        schema_types = node.get("type")
        if isinstance(schema_types, list) and len(schema_types) > 1:
            union_properties += 1

    return (
        optional_properties > _ANTHROPIC_MAX_OPTIONAL_PROPERTIES
        or union_properties > _ANTHROPIC_MAX_UNION_PROPERTIES
    )


def _without_ref_siblings(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove JSON Schema keywords providers reject beside ``$ref``."""
    normalized = deepcopy(schema)
    for node in _walk_json_schema(normalized):
        if "$ref" not in node:
            continue
        for key in tuple(node):
            if key != "$ref" and not key.startswith("$"):
                del node[key]
    return normalized


@lru_cache(maxsize=1)
def _compatible_openai_chat_class():
    from agno.models.openai import OpenAIChat

    class CompatibleOpenAIChat(OpenAIChat):
        """OpenAI adapter that emits legal reference nodes for response_format."""

        def get_request_params(
            self,
            response_format=None,
            tools=None,
            tool_choice=None,
            run_response=None,
        ):
            params = super().get_request_params(
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                run_response=run_response,
            )
            json_schema = params.get("response_format", {}).get("json_schema", {})
            schema = json_schema.get("schema")
            if isinstance(schema, dict):
                json_schema["schema"] = _without_ref_siblings(schema)
            return params

    return CompatibleOpenAIChat


@lru_cache(maxsize=1)
def _compatible_gemini_class():
    from agno.models.google import Gemini

    class CompatibleGemini(Gemini):
        """Gemini adapter that preserves dictionaries and referenced item types."""

        def get_request_params(
            self,
            system_message=None,
            response_format=None,
            tools=None,
            tool_choice=None,
        ):
            if not (
                isinstance(response_format, type)
                and issubclass(response_format, BaseModel)
            ):
                return super().get_request_params(
                    system_message=system_message,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                )

            params = super().get_request_params(
                system_message=system_message,
                response_format=None,
                tools=tools,
                tool_choice=tool_choice,
            )
            config = params.get("config")
            if config is None:
                from google.genai.types import GenerateContentConfig

                config = GenerateContentConfig()
                params["config"] = config
            config.response_mime_type = "application/json"
            config.response_schema = None
            config.response_json_schema = _without_ref_siblings(
                response_format.model_json_schema()
            )
            return params

    return CompatibleGemini


def use_json_mode_for(model: Any, output_schema: Any = None) -> bool:
    """Whether an ``output_schema`` agent over ``model`` must use JSON mode.

    Providers without native/json_schema structured outputs (e.g. DeepSeek)
    honour an ``output_schema`` only via ``response_format`` JSON mode; without
    it they intermittently return prose that agno cannot parse, falling back to
    the raw ``str``. Providers with native support keep their stricter
    structured outputs unless a Claude schema exceeds Anthropic's grammar
    limits; oversized Claude schemas use JSON mode plus local Pydantic
    validation instead of failing the request with HTTP 400.
    """
    if not getattr(model, "supports_native_structured_outputs", False):
        return True
    return getattr(
        model, "provider", None
    ) == "Anthropic" and _anthropic_schema_exceeds_limits(output_schema)


def build_model(
    model_id: str,
    api_key: str | None = None,
    *,
    cache_system_prompt: bool = False,
    reasoning: bool = False,
) -> Any:
    """Construct the agno model for a (possibly provider-prefixed) ``model_id``.

    Provider SDK modules are imported lazily, per branch: a Claude-only run never
    imports ``openai`` or ``google-genai``, and a missing optional SDK fails only
    when that provider is actually selected. ``cache_system_prompt`` is forwarded
    only to Anthropic; other providers ignore it.
    """
    provider, model = split_provider(model_id)
    reasoning = reasoning and provider_capabilities(model_id).supports_reasoning
    key = api_key or resolve_api_key(model_id) or None
    if provider == "openai":
        OpenAIChat = _compatible_openai_chat_class()

        return OpenAIChat(
            id=model,
            api_key=key,
            reasoning_effort="high" if reasoning else None,
        )
    if provider == "gemini":
        Gemini = _compatible_gemini_class()

        # Gemini treats an unset thinking config as "provider decides" (an
        # automatic, unbounded budget) rather than off, so a non-reasoning agent
        # has to bound it explicitly -- but HOW differs by model generation.
        #
        # Gemini 3 replaced thinking_budget with thinking_level and rejects the
        # budget outright: thinking_budget=0 fails the entire request with 400
        # INVALID_ARGUMENT before any generation, which agno then surfaces as a
        # plain str (the error body) rather than the output_schema. Bound it
        # with thinking_level="low" instead; that reports no thought tokens.
        # Pre-3 ids have no thinking_level, so there 0 is still the way off.
        if model.casefold().startswith("gemini-3"):
            return Gemini(
                id=model,
                api_key=key,
                thinking_level="high" if reasoning else "low",
            )
        return Gemini(
            id=model,
            api_key=key,
            thinking_level="high" if reasoning else None,
            thinking_budget=None if reasoning else 0,
        )
    if provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(
            id=model,
            api_key=key,
            use_thinking=True if reasoning else None,
            reasoning_effort="max" if reasoning else None,
        )
    from agno.models.anthropic import Claude

    return Claude(
        id=model,
        api_key=key,
        cache_system_prompt=cache_system_prompt,
        thinking={"type": "adaptive"} if reasoning else None,
        output_config={"effort": "high"} if reasoning else None,
    )


def build_search_equipped(
    model_id: str,
    mode: SearchMode | None = None,
    *,
    reasoning: bool = False,
    cache_system_prompt: bool = False,
) -> tuple[Any, list[Any]]:
    """Build a model and its search tools for advisor research."""
    settings = get_settings()
    plan = plan_search(model_id, mode or settings.search_mode)
    if plan.strategy == "none":
        raise ValueError("advisor web search is disabled by search_mode=off")
    _provider, model_name = split_provider(model_id)
    api_key = resolve_api_key(model_id) or None
    reasoning = reasoning and provider_capabilities(model_id).supports_reasoning

    if plan.strategy == "native_openai":
        from agno.models.openai.responses import OpenAIResponses

        return (
            OpenAIResponses(
                id=model_name,
                api_key=api_key,
                reasoning_effort="high" if reasoning else None,
                store=False,
            ),
            [OPENAI_WEB_SEARCH_TOOL],
        )
    if plan.strategy == "native_gemini":
        from agno.models.google.gemini_interactions import GeminiInteractions

        return (
            GeminiInteractions(
                id=model_name,
                api_key=api_key,
                search=True,
                thinking_level="high" if reasoning else None,
                store=False,
            ),
            [],
        )

    model = build_model(
        model_id,
        api_key=api_key,
        cache_system_prompt=cache_system_prompt,
        reasoning=reasoning,
    )
    if plan.strategy == "native_anthropic":
        return model, [anthropic_web_search_tool(model_id)]
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
        raise ValueError(
            f"no API key configured for transcription provider {provider!r}"
        )
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
