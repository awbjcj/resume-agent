import asyncio
import logging
import re
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from inspect import isawaitable
from types import SimpleNamespace
from typing import Any, Literal, Protocol, TypeVar, cast

import httpx
from pydantic import BaseModel

from resume_agent.agent_trace import record_agent_run
from resume_agent.config import Settings, get_settings
from resume_agent.career_skills.models import AgentRunMeta
from resume_agent.sessions.stream import (
    Completed,
    Failed,
    ReasoningDelta,
    StreamEvent,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)

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


class _UnparsedRetry(Exception):
    """Internal signal: a structured run came back unparsed and may be retried.

    Never escapes ``AgentRunner``; the last response is returned instead so the
    call site's ``expect_schema`` raises its own rich diagnostic.
    """

    def __init__(self, response: Any) -> None:
        super().__init__("agent returned unparsed structured output")
        self.response = response


def _unparsed_structured_output(agent: Any, response: Any) -> bool:
    """Whether a completed run failed to produce the schema it was asked for.

    agno does not raise when it cannot coerce a response into ``output_schema``
    -- it leaves ``RunOutput.content`` as the raw ``str``. That is a *successful*
    provider call, so nothing in the transient-error path sees it and the single
    bad parse goes straight to whatever fallback the caller has. Detected here,
    where the retry budget already lives, so one malformed body costs a retry
    rather than a degraded result.
    """
    schema = getattr(agent, "output_schema", None)
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        return False
    return not isinstance(getattr(response, "content", None), schema)


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


def _agent_model_id(agent: Any) -> str:
    """The provider-prefixed model id an agent's model represents.

    The prefix is what ``split_provider`` reads, and a bare id means Anthropic,
    so an Anthropic model is deliberately left unprefixed rather than being
    written ``anthropic:...``.
    """
    model = getattr(agent, "model", None)
    if model is None:
        return str(getattr(agent, "model_id", "") or "")
    name = str(getattr(model, "id", "") or "")
    if not name:
        return ""
    provider_value = getattr(model, "provider", None)
    get_provider = getattr(model, "get_provider", None)
    if not provider_value and callable(get_provider):
        provider_value = get_provider()
    from resume_agent.tenancy.costs import normalize_provider

    provider = normalize_provider(str(provider_value or ""))
    if not provider or provider == "anthropic":
        return name
    return f"{provider}:{name}"


def record_call(agent: Any, response: Any) -> None:
    """Forward to the usage recorder through its module.

    Imported by attribute rather than by name so a test (or the perf harness)
    that patches ``tenancy.usage.record_call`` is honoured here too — binding
    the function at import time would silently bypass every such patch.
    """
    from resume_agent.tenancy import usage

    usage.record_call(agent, response)


class AgentRunner:
    """Adapter that narrows third-party agent APIs to ``run`` / ``arun``."""

    def __init__(
        self,
        agent: Any,
        *,
        run_meta: AgentRunMeta | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._agent = agent
        self._run_meta = run_meta
        self._settings = settings
        # One agno model object is shared by every coroutine in a fan-out, and
        # applying a key nulls its cached clients. The lock plus the in-flight
        # count are what stop a key change from pulling the client out from
        # under a sibling request mid-flight.
        self._key_lock = threading.Lock()
        self._inflight = 0
        self._applied_key: str | None = None

    @property
    def agent(self) -> Any:
        """The wrapped provider agent, for per-run system-block binding."""
        return self._agent

    @property
    def run_meta(self) -> AgentRunMeta | None:
        return self._run_meta

    def _enter(self, settings: Settings) -> None:
        """Resolve spend policy, apply the funded key, and count the call in.

        Raises the same budget errors ``enforce_agent_budget`` always raised.
        Must be paired with :meth:`_exit`, but only when it returns.
        """
        from resume_agent.tenancy.spend import SpendGate

        model = getattr(self._agent, "model", None)
        model_id = _agent_model_id(self._agent)
        if model is None or not model_id:
            with self._key_lock:
                self._inflight += 1
            return
        decision = SpendGate(settings=self._settings).open(model_id)
        with self._key_lock:
            self._apply_locked(model, decision)
            self._inflight += 1

    def _apply_locked(self, model: Any, decision: Any) -> None:
        from resume_agent.tenancy.context import current_context

        context = current_context()
        if context is not None:
            context.selected_model_own_keys[id(model)] = decision.own_key
        key = decision.api_key or None
        if key == self._applied_key and getattr(model, "api_key", None) == key:
            return
        if self._inflight:
            # A sibling is mid-request on this model's client. Nulling it now
            # would fail that call; the change lands on the next call that
            # finds the runner idle, which is the next phase in practice.
            return
        model.api_key = key
        # Agno caches clients after first use. Clearing them makes the next
        # request honor the newly selected credential.
        if hasattr(model, "client"):
            model.client = None
        if hasattr(model, "async_client"):
            model.async_client = None
        self._applied_key = key

    def _exit(self) -> None:
        with self._key_lock:
            self._inflight -= 1

    def run(self, prompt: str) -> Any:
        settings = self._settings or get_settings()
        for attempt in range(settings.llm_retries + 1):
            try:
                self._enter(settings)
                try:
                    response = self._agent.run(prompt)
                finally:
                    self._exit()
                record_call(self._agent, response)
                record_agent_run(self, response, retries=attempt)
                if _unparsed_structured_output(self._agent, response):
                    raise _UnparsedRetry(response)
                return response
            except _UnparsedRetry as unparsed:
                if attempt >= settings.llm_retries:
                    return unparsed.response
                logger.warning(
                    "agent returned unparsed structured output; retrying (%d/%d)",
                    attempt + 1,
                    settings.llm_retries,
                )
                time.sleep(settings.llm_retry_delay * (2**attempt))
            except Exception as exc:
                if attempt >= settings.llm_retries or not is_transient(exc):
                    record_agent_run(
                        self, None, retries=attempt, status="error", error=str(exc)
                    )
                    raise
                time.sleep(settings.llm_retry_delay * (2**attempt))
        raise AssertionError("unreachable")

    async def arun(self, prompt: str) -> Any:
        settings = self._settings or get_settings()
        for attempt in range(settings.llm_retries + 1):
            try:
                # Both hops are synchronous SQLite I/O, and one of them can
                # wait on a write lock. On the event loop that the concurrent
                # fan-out shares, that stalls every sibling call in the batch.
                await asyncio.to_thread(self._enter, settings)
                try:
                    response = await self._agent.arun(prompt)
                finally:
                    self._exit()
                await asyncio.to_thread(record_call, self._agent, response)
                record_agent_run(self, response, retries=attempt)
                if _unparsed_structured_output(self._agent, response):
                    raise _UnparsedRetry(response)
                return response
            except _UnparsedRetry as unparsed:
                if attempt >= settings.llm_retries:
                    return unparsed.response
                logger.warning(
                    "agent returned unparsed structured output; retrying (%d/%d)",
                    attempt + 1,
                    settings.llm_retries,
                )
                await asyncio.sleep(settings.llm_retry_delay * (2**attempt))
            except Exception as exc:
                if attempt >= settings.llm_retries or not is_transient(exc):
                    record_agent_run(
                        self, None, retries=attempt, status="error", error=str(exc)
                    )
                    raise
                await asyncio.sleep(settings.llm_retry_delay * (2**attempt))
        raise AssertionError("unreachable")

    def stream(self, prompt: str) -> Iterator[StreamEvent]:
        """Yield provider-neutral events, retrying only before visible output."""
        settings = self._settings or get_settings()
        for attempt in range(settings.llm_retries + 1):
            emitted = False
            try:
                self._enter(settings)
                try:
                    raw_stream = self._agent.run(
                        prompt,
                        stream=True,
                        stream_events=True,
                        yield_run_output=True,
                    )
                finally:
                    self._exit()
                terminal_output: Any | None = None
                for raw in raw_stream:
                    tag = _stream_event_tag(raw)
                    if tag is None:
                        terminal_output = raw
                        continue
                    for event in _map_stream_event(tag, raw):
                        if isinstance(event, Failed):
                            yield event
                            return
                        emitted = True
                        yield event
                if terminal_output is None:
                    yield Failed(
                        "The model stream ended without a final response.",
                        "MISSING_RUN_OUTPUT",
                    )
                    return
                record_call(self._agent, terminal_output)
                if _run_failed(terminal_output):
                    message = (
                        getattr(terminal_output, "content", None)
                        or "The model reported an error."
                    )
                    yield Failed(str(message), "RUN_ERROR")
                    return
                yield Completed(terminal_output)
                return
            except Exception as exc:
                if emitted or attempt >= settings.llm_retries or not is_transient(exc):
                    yield Failed(str(exc), type(exc).__name__)
                    return
                time.sleep(settings.llm_retry_delay * (2**attempt))
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


def _stream_event_tag(raw: Any) -> str | None:
    """Return Agno's stable event value; a terminal RunOutput has no event."""
    event = getattr(raw, "event", None)
    if event is None:
        return None
    value = getattr(event, "value", event)
    return value if isinstance(value, str) and value else ""


def _stream_preview(value: object, limit: int = 160) -> str:
    text = value if isinstance(value, str) else repr(value)
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _map_stream_event(tag: str, raw: Any) -> list[StreamEvent]:
    """Map one pinned-Agno event to zero or more stable application events."""
    if tag in {"RunContent", "RunIntermediateContent"}:
        events: list[StreamEvent] = []
        reasoning = getattr(raw, "reasoning_content", None)
        content = getattr(raw, "content", None)
        # A provider adapter that hands back the visible answer as "reasoning"
        # is not giving us reasoning. Forwarding the echo alternates the two
        # event kinds on every delta, which flushes the sink per token and
        # splits the reply into one disclosure plus one markdown block per
        # token. `build_model` stops OpenAI producing the echo in the first
        # place; this keeps the seam honest for any provider that does.
        if isinstance(reasoning, str) and reasoning and reasoning != content:
            events.append(ReasoningDelta(reasoning))
        if isinstance(content, str) and content:
            events.append(TextDelta(content))
        return events
    if tag == "ReasoningContentDelta":
        content = getattr(raw, "reasoning_content", None) or getattr(raw, "content", "")
        return [ReasoningDelta(content)] if isinstance(content, str) and content else []
    if tag == "ToolCallStarted":
        tool = getattr(raw, "tool", None)
        name = str(getattr(tool, "tool_name", "") or "tool")
        call_id = str(getattr(tool, "tool_call_id", "") or name)
        return [
            ToolStarted(call_id, name, _stream_preview(getattr(tool, "tool_args", "")))
        ]
    if tag in {"ToolCallCompleted", "ToolCallError"}:
        tool = getattr(raw, "tool", None)
        name = str(getattr(tool, "tool_name", "") or "tool")
        call_id = str(getattr(tool, "tool_call_id", "") or name)
        error = getattr(raw, "error", None) or getattr(tool, "tool_call_error", None)
        ok = tag == "ToolCallCompleted" and not error
        result = error if error else getattr(tool, "result", "")
        return [ToolCompleted(call_id, name, _stream_preview(result), ok)]
    if tag == "RunError":
        message = getattr(raw, "content", None) or "The model reported an error."
        code = getattr(raw, "error_type", None) or "RunError"
        return [Failed(str(message), str(code))]
    if tag == "RunCancelled":
        message = getattr(raw, "reason", None) or "cancelled"
        return [Failed(str(message), "CANCELLED")]
    return []


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


#: Where a provider adapter records "this response did not finish". Rides
#: agno's own ``ModelResponse.provider_data``, which ``agent/_response.py``
#: copies onto ``RunOutput.model_provider_data`` -- the only channel that
#: survives from the model adapter to the ``expect_*`` seams without either
#: mutating the shared model object (one agno model serves every coroutine in a
#: concurrent batch) or raising, which agno's ``invoke`` would rewrap as a
#: ``ModelProviderError`` and hide from callers that catch ``UnparsedAgentOutput``.
INCOMPLETE_KEY = "resume_agent_incomplete"


def _incomplete_detail(result: Any) -> dict[str, Any] | None:
    """The truncation record a provider adapter left on this run, if any."""
    data = getattr(result, "model_provider_data", None)
    if not isinstance(data, dict):
        return None
    detail = data.get(INCOMPLETE_KEY)
    return detail if isinstance(detail, dict) else None


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


def _describe_unparsed(result: Any, content: Any, headline: str) -> str:
    """Build the failure message, reading every field defensively.

    ``RunOutput``'s shape drifts between agno versions, so a missing attribute
    must degrade the report rather than raise over the failure it describes.
    Shared by ``expect_schema`` and ``expect_text`` so both failures carry the
    same model/status/token diagnostics.
    """
    fields = [headline]
    provider = getattr(result, "model_provider", None)
    model = getattr(result, "model", None)
    if provider or model:
        fields.append(f"model={provider or '?'}:{model or '?'}")
    status = getattr(result, "status", None)
    if status is not None:
        fields.append(f"status={getattr(status, 'value', status)}")
    # The one fact that separates a truncation from a refusal or a rejected
    # request -- all three of which otherwise read as "got str". Providers report
    # a finished-but-incomplete response as a *success*, so `status` above says
    # `completed` and only this names the ceiling that stopped generation.
    incomplete = _incomplete_detail(result)
    if incomplete is not None:
        fields.append(
            f"cut off: reason={incomplete.get('reason') or '?'} "
            f"ceiling={incomplete.get('ceiling') or '?'}"
        )
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
    headline = (
        f"Expected {schema.__name__} from {source} agent, got {type(content).__name__}"
    )
    raise UnparsedAgentOutput(_describe_unparsed(result, content, headline))


def _run_failed(result: Any) -> bool:
    """Whether agno marked this run as errored.

    Read defensively and by value: ``status`` is a ``str`` Enum whose member
    set drifts between agno versions, and a missing attribute must not be
    mistaken for a failure.
    """
    status = getattr(result, "status", None)
    return str(getattr(status, "value", status) or "").casefold() == "error"


def expect_text(result: Any, *, source: str) -> str:
    """Return ``result.content`` as usable prose, or raise saying why it is not.

    The plain-text counterpart to ``expect_schema``, and it exists for the same
    reason: **agno does not raise when a provider rejects a request.** It logs,
    sets ``RunOutput.status`` to ``ERROR``, and -- because ``content`` was still
    ``None`` -- assigns the provider's error body to ``content`` as a plain
    ``str``. A structured call site notices, because an error body is not the
    schema. A free-text one cannot tell an error body from a real answer.

    That gap is how a hard 400 ("Function tools with reasoning_effort are not
    supported for gpt-5.6-terra in /v1/chat/completions") reached the coach's
    formatter dressed as coach notes, and surfaced two layers downstream as the
    nonsensical ``TurnRejected: opening turn proposed no topics`` -- in a
    different file, with a message that never mentions the provider.

    Blank prose is rejected too: it is as unusable to a downstream formatter as
    an error body, and silently formatting it produces the same empty agenda.

    Truncated prose is the third case, and the one this seam used to wave
    through: a structured call notices a response cut off at the output-token
    ceiling (half a JSON body parses as nothing), but half a *sentence* is a
    non-empty ``str`` on a run the provider reports as successful. It passed
    both checks above and reached the caller as a whole answer.
    """
    content = getattr(result, "content", None)
    truncated = _incomplete_detail(result) is not None
    if (
        not truncated
        and not _run_failed(result)
        and isinstance(content, str)
        and content.strip()
    ):
        return content
    if truncated:
        reason = "cut off before finishing"
    else:
        reason = "run failed" if _run_failed(result) else "no usable text"
    headline = (
        f"Expected prose from {source} agent, got {type(content).__name__} ({reason})"
    )
    raise UnparsedAgentOutput(_describe_unparsed(result, content, headline))


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
    reasoning_efforts: tuple[str, ...] = ()


GeminiInteractionsThinkingLevel = Literal["minimal", "low", "medium", "high"]


# Curated model choices per provider for the tier pickers, so a UI can offer a
# closed dropdown instead of free text a user could mistype. Ids follow the
# same ``provider:model`` convention as everywhere else in this module — bare
# ids are Anthropic. Update this list as providers ship new models.
MODEL_CATALOG: dict[str, list[ModelCatalogEntry]] = {
    "anthropic": [
        ModelCatalogEntry("claude-haiku-4-5", "Claude Haiku 4.5"),
        ModelCatalogEntry(
            "claude-sonnet-5",
            "Claude Sonnet 5",
            ("low", "medium", "high", "xhigh", "max"),
        ),
        ModelCatalogEntry(
            "claude-opus-4-8",
            "Claude Opus 4.8",
            ("low", "medium", "high", "xhigh", "max"),
        ),
        ModelCatalogEntry(
            "claude-opus-5", "Claude Opus 5", ("low", "medium", "high", "xhigh", "max")
        ),
    ],
    "openai": [
        ModelCatalogEntry(
            "openai:gpt-5.6-luna",
            "GPT-5.6 Luna",
            ("none", "low", "medium", "high", "xhigh", "max"),
        ),
        ModelCatalogEntry(
            "openai:gpt-5.6-terra",
            "GPT-5.6 Terra",
            ("none", "low", "medium", "high", "xhigh", "max"),
        ),
        ModelCatalogEntry(
            "openai:gpt-5.6-sol",
            "GPT-5.6 Sol",
            ("none", "low", "medium", "high", "xhigh", "max"),
        ),
        ModelCatalogEntry(
            "openai:gpt-5.5-pro",
            "GPT-5.5 Pro",
            ("medium", "high", "xhigh"),
        ),
        ModelCatalogEntry(
            "openai:gpt-5.5",
            "GPT-5.5",
            ("none", "low", "medium", "high", "xhigh"),
        ),
        ModelCatalogEntry(
            "openai:gpt-5.4-mini",
            "GPT-5.4 Mini",
            ("none", "low", "medium", "high", "xhigh"),
        ),
    ],
    "gemini": [
        ModelCatalogEntry(
            "gemini:gemini-3.5-flash-lite",
            "Gemini 3.5 Flash Lite",
            ("minimal", "low", "medium", "high"),
        ),
        ModelCatalogEntry(
            "gemini:gemini-3.1-flash-lite",
            "Gemini 3.1 Flash Lite",
            ("low", "medium", "high"),
        ),
        ModelCatalogEntry(
            "gemini:gemini-3.6-flash",
            "Gemini 3.6 Flash",
            ("minimal", "low", "medium", "high"),
        ),
        ModelCatalogEntry(
            "gemini:gemini-3.5-flash",
            "Gemini 3.5 Flash",
            ("minimal", "low", "medium", "high"),
        ),
        ModelCatalogEntry(
            "gemini:gemini-3.1-pro-preview",
            "Gemini 3.1 Pro (Preview)",
            ("low", "medium", "high"),
        ),
    ],
    "deepseek": [
        # On the Responses API `reasoning.effort` is BOTH the thinking toggle and
        # the effort dial -- `none` disables thinking outright -- so `none` belongs
        # in the declared vocabulary. `_responses_effort` picks the lowest declared
        # effort for a non-reasoning agent, which is what turns thinking off.
        # DeepSeek maps a requested effort to an actual one as
        # low->low, medium->high, high->high, xhigh->high, max->max, so only these
        # four are distinct.
        ModelCatalogEntry(
            "deepseek:deepseek-v4-flash",
            "DeepSeek V4 Flash",
            ("none", "low", "high", "max"),
        ),
        ModelCatalogEntry(
            "deepseek:deepseek-v4-pro",
            "DeepSeek V4 Pro",
            ("none", "low", "high", "max"),
        ),
    ],
}


def catalog_entry(model_id: str) -> ModelCatalogEntry | None:
    """Return curated capabilities for a selectable model, if known."""
    return next(
        (
            entry
            for entries in MODEL_CATALOG.values()
            for entry in entries
            if entry.id == model_id
        ),
        None,
    )


OPENAI_WEB_SEARCH_TOOL = {"type": "web_search"}

#: DeepSeek executes `web_search` server-side on the Responses API, and its tool
#: definition is byte-identical to OpenAI's. It is kept as a separate name rather
#: than aliased because the two are only incidentally equal -- DeepSeek ignores
#: `search_context_size`/`user_location`, and returns **no** `url_citation`
#: annotations, which is why `provider_capabilities` still reports
#: `supports_native_citations=False` for it.
DEEPSEEK_WEB_SEARCH_TOOL = {"type": "web_search"}

# Claude ids name their family before the version (``claude-opus-4-8``,
# ``claude-sonnet-5``, ``claude-haiku-4-5-20251001``). Pre-4 ids used the
# opposite order (``claude-3-5-haiku-20241022``) and deliberately do not match,
# so they classify as legacy -- which is exactly right, since every capability
# gated on this parser arrived with the 4.6 generation.
_ANTHROPIC_VERSION = re.compile(
    r"^claude-(?:opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d+))?"
)
# Adaptive thinking, `output_config.effort`, and the dynamic-filtering
# web-search tool all require this generation or newer.
_ANTHROPIC_MODERN = (4, 6)
# Thinking is always on for these families; an explicit disabled config is a 400.
_ANTHROPIC_ALWAYS_THINKING = ("claude-fable-", "claude-mythos-")


def anthropic_version(model: str) -> tuple[int, int] | None:
    """Parse a bare Claude id into a comparable ``(major, minor)``, or ``None``.

    ``None`` means "older than the 4.x family, or not a recognizable Claude id" --
    treat it as supporting none of the 4.6+ request surface.
    """
    match = _ANTHROPIC_VERSION.match(model.casefold())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def anthropic_web_search_tool(model_id: str) -> dict[str, Any]:
    """Pick the Anthropic web-search tool variant for a (possibly bare) Claude model id.

    ``web_search_20260209`` (dynamic filtering) requires Opus 4.6+ / Sonnet 4.6+;
    anything older -- Haiku 4.5, and any pre-4.6 id reachable through the custom
    model field -- must get the basic ``web_search_20250305`` or the Messages API
    rejects the tool definition with a 400 before any search runs.
    """
    _provider, model = split_provider(model_id)
    version = anthropic_version(model)
    modern = version is not None and version >= _ANTHROPIC_MODERN
    tool_type = "web_search_20260209" if modern else "web_search_20250305"
    return {"type": tool_type, "name": "web_search", "max_uses": 5}


SearchMode = Literal["auto", "native", "tool", "off"]
SearchStrategy = Literal[
    "none",
    "tool",
    "native_anthropic",
    "native_openai",
    "native_gemini",
    "native_deepseek",
]
_NATIVE_SEARCH_STRATEGIES: dict[str, SearchStrategy] = {
    "anthropic": "native_anthropic",
    "openai": "native_openai",
    "gemini": "native_gemini",
    "deepseek": "native_deepseek",
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
        # Reasoning means `thinking={"type": "adaptive"}` + `output_config.effort`,
        # and BOTH arrived with the 4.6 generation: adaptive is rejected on 4.5 and
        # older (they need `{"type": "enabled", "budget_tokens": N}`), and `effort`
        # errors outright on Sonnet 4.5 / Haiku 4.5. agno cannot catch this for us --
        # its NON_THINKING_MODELS guard only covers the Haiku 3 and 3.5 families --
        # so a pre-4.6 id would reach the API and 400 at runtime.
        version = anthropic_version(model)
        reasoning = version is not None and version >= _ANTHROPIC_MODERN
        return ProviderCapabilities(reasoning, True, True)
    if provider == "openai" and folded.startswith(("gpt-", "o1", "o3", "o4")):
        return ProviderCapabilities(
            folded.startswith(("gpt-5", "o1", "o3", "o4")), True, True
        )
    if provider == "gemini" and folded.startswith("gemini-"):
        return ProviderCapabilities(
            folded.startswith(("gemini-3", "gemini-2.5")), True, True
        )
    if provider == "deepseek" and folded.startswith("deepseek-"):
        # Citations stay False: DeepSeek's native web_search runs server-side but
        # returns no `url_citation` annotations (verified live on both tool-type
        # strings), so there is nothing for a citation renderer to read.
        return ProviderCapabilities(folded.startswith("deepseek-v4"), False, True)
    return _NO_PROVIDER_CAPABILITIES


def supports_native_search(model_id: str) -> bool:
    """Whether ``model_id``'s provider gets provider-native web search.

    Every supported provider now has one. A provider outside this set still gets
    search under ``search_mode=auto`` — ``plan_search`` falls back to the
    DuckDuckGo tool — just not the higher-quality native variant.
    """
    provider, _model = split_provider(model_id)
    return provider in _NATIVE_SEARCH_STRATEGIES


def _settings_provider_key(settings: Settings, provider: str) -> str:
    return {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "deepseek": settings.deepseek_api_key,
    }.get(provider, "")


def resolve_api_key(model_id: str, *, settings: Settings | None = None) -> str:
    """Select the shared provider key first, then fall back to the user's key.

    The non-raising half of the spend seam. It shares one cached policy
    evaluation with the enforcing half, so "which key?" and "may I spend?" can
    no longer be answered from two independently derived views of the same five
    facts.
    """
    from resume_agent.tenancy.spend import SpendGate

    return SpendGate(settings=settings).select(model_id).api_key


def model_access_available(model_id: str, *, settings: Settings | None = None) -> bool:
    """Whether the active user can fund a call to ``model_id`` right now."""

    provider, model = split_provider(model_id)
    from resume_agent.tenancy.context import current_context

    context = current_context()
    if context is not None:
        if context.user_provider_keys.get(provider):
            return True
        if context.platform_provider_keys.get(provider):
            from resume_agent.tenancy.limits import shared_key_available

            return shared_key_available(provider, model)
    return bool(_settings_provider_key(settings or get_settings(), provider))


def provider_access_available(
    provider: str, *, settings: Settings | None = None
) -> bool:
    """Whether any catalogued model for ``provider`` is currently usable."""

    return any(
        model_access_available(entry.id, settings=settings)
        for entry in MODEL_CATALOG.get(provider, ())
    )


def refresh_agent_api_key(agent: object, *, settings: Settings | None = None) -> None:
    """Refresh a reusable agent when its shared allowance changes key source."""

    from resume_agent.tenancy.context import current_context
    from resume_agent.tenancy.costs import normalize_provider

    context = current_context()
    model = getattr(agent, "model", None)
    if context is None or model is None:
        return
    provider_value = getattr(model, "provider", None)
    get_provider = getattr(model, "get_provider", None)
    if not provider_value and callable(get_provider):
        provider_value = get_provider()
    provider = normalize_provider(str(provider_value or ""))
    if (
        provider not in context.platform_provider_keys
        and provider not in context.user_provider_keys
    ):
        return
    model_name = str(getattr(model, "id", "") or "")
    if not provider or not model_name:
        return
    model_id = model_name if provider == "anthropic" else f"{provider}:{model_name}"
    selected = resolve_api_key(model_id, settings=settings) or None
    context.selected_model_own_keys[id(model)] = context.selected_own_key_providers[
        provider
    ]
    if getattr(model, "api_key", None) == selected:
        return
    model.api_key = selected
    # Agno caches clients after first use. Clearing them makes the next request
    # honor the newly selected credential instead of retaining the old client.
    if hasattr(model, "client"):
        model.client = None
    if hasattr(model, "async_client"):
        model.async_client = None


def missing_model_keys(settings: Settings) -> list[str]:
    """Configured mid/cheap tier models whose provider key is absent.

    Returns ``"tier (model)"`` labels for surfaces that gate LLM features on
    key presence (coach router, interview router, coach CLI).
    """
    configured = (("mid", settings.mid_model), ("cheap", settings.cheap_model))
    return [
        f"{tier} ({model})"
        for tier, model in configured
        if not resolve_api_key(model, settings=settings)
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
def _compatible_openai_responses_class():
    from agno.models.openai.responses import OpenAIResponses

    class CompatibleOpenAIResponses(OpenAIResponses):
        """Emit legal reference nodes, omit empty reasoning, keep truncation."""

        def _parse_provider_response(self, response, **kwargs):
            """Preserve "this response stopped early" past agno's parser.

            agno reads ``status == "incomplete"``, logs it under a misleading
            "Background response ..." headline (the check sits outside the
            background branch, so it fires for every non-streaming call), and
            then drops it: ``_parse_provider_response`` gets the whole
            ``Response`` but copies neither the status nor
            ``incomplete_details`` onto ``ModelResponse``. The truncated body
            then flows into three JSON parsers, fails all of them, and reaches
            ``expect_schema`` as a bare ``str`` -- indistinguishable from a
            refusal or a rejected schema, which is the difference between
            "raise the output budget" and "fix the prompt".

            Recorded rather than raised: agno's ``invoke`` rewraps any
            exception as ``ModelProviderError``, which would lose the type
            anyway *and* escape call sites that deliberately degrade on
            ``UnparsedAgentOutput``.
            """
            parsed = super()._parse_provider_response(response, **kwargs)
            if getattr(response, "status", None) != "incomplete":
                return parsed
            details = getattr(response, "incomplete_details", None)
            if parsed.provider_data is None:
                parsed.provider_data = {}
            parsed.provider_data[INCOMPLETE_KEY] = {
                "reason": getattr(details, "reason", None) or str(details or "unknown"),
                "ceiling": self.max_output_tokens,
            }
            return parsed

        def get_request_params(
            self,
            messages=None,
            response_format=None,
            tools=None,
            tool_choice=None,
        ):
            params = super().get_request_params(
                messages=messages,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
            )
            text_format = params.get("text", {}).get("format", {})
            schema = text_format.get("schema")
            if isinstance(schema, dict):
                text_format["schema"] = _without_ref_siblings(schema)
            if not params.get("reasoning"):
                params.pop("reasoning", None)
            return params

    return CompatibleOpenAIResponses


@lru_cache(maxsize=1)
def _compatible_deepseek_responses_class():
    """DeepSeek on the Responses API, with agno's reasoning defects corrected.

    Subclasses the OpenAI Responses adapter because DeepSeek serves the same
    wire format at its own ``base_url`` -- which also inherits the truncation
    recording and ``$ref``-sibling stripping that class already does.
    """
    OpenAIResponses = _compatible_openai_responses_class()

    @dataclass
    class CompatibleDeepSeekResponses(OpenAIResponses):  # type: ignore[valid-type,misc]
        id: str = "deepseek-v4-flash"
        name: str = "DeepSeek"
        # Load-bearing, not cosmetic: `tenancy.costs.normalize_provider` tests
        # for "openai" BEFORE "deepseek", so inheriting the parent's "OpenAI"
        # would bill every DeepSeek call against the OpenAI budget, select the
        # OpenAI key, and mislabel `_agent_model_id` as `openai:deepseek-...`.
        provider: str = "DeepSeek"
        base_url: str | httpx.URL | None = "https://api.deepseek.com"
        # DeepSeek's `strict` gates VALIDATION OF THE REQUEST SCHEMA, not
        # constrained decoding of the response -- unlike OpenAI, where a strict
        # schema is compiled into a grammar that makes a stray key or a
        # wrong-typed field impossible to emit. Measured against instructions
        # that deliberately violate the schema: strict=True still returned a
        # wrong-typed field 6/6 and leaked an undeclared key 5/6, versus 6/6 and
        # 6/6 for strict=False. It enforces nothing.
        #
        # What it does do is reject a bare `anyOf` -- the shape pydantic emits
        # for EVERY Optional field -- with `400 Invalid json schema: field
        # `anyOf`: missing field `type``. Satisfying that needs a sibling
        # `type`, which must be a single scalar (a list is rejected, and so is
        # `object`), so a nullable OBJECT field can only be annotated `null`.
        # Measured across `FitScore` and `JobCriteriaExtract` at n=10 per arm,
        # strict=True + that annotation was indistinguishable from strict=False
        # on the raw schema: 10/10 valid and 10/10 populated on every
        # nullable-object field either way. So the rewrite bought nothing, and
        # the one future in which it starts mattering is the bad one -- if
        # DeepSeek ever implements real constrained decoding, `type: "null"`
        # becomes a real constraint and silently nulls those fields.
        #
        # Sending the same unmodified schema OpenAI gets is therefore both
        # simpler and safer. `expect_schema` + pydantic remain the real gate,
        # which is where enforcement actually lives for this provider.
        strict_output: bool = False

        def _parse_provider_response(self, response, **kwargs):
            """Hand back DeepSeek's real chain-of-thought, not an echo of the answer.

            agno looks for reasoning in a reasoning item's ``summary``. DeepSeek
            documents that ``reasoning.summary`` is "accepted but no summary is
            generated", and live responses confirm it: ``summary`` is always
            ``[]`` while the actual reasoning sits in
            ``content[].text`` under ``type == "reasoning_text"``. Finding no
            summary, agno falls through to ``reasoning_content =
            response.output_text`` -- copying the visible answer into the
            reasoning channel on **every** non-streaming call. Sending
            ``reasoning_summary="auto"`` does not prevent this; that only guards
            the streaming branch.
            """
            parsed = super()._parse_provider_response(response, **kwargs)
            texts: list[str] = []
            for item in getattr(response, "output", None) or []:
                if getattr(item, "type", None) != "reasoning":
                    continue
                for part in getattr(item, "content", None) or []:
                    text = (
                        part.get("text")
                        if isinstance(part, dict)
                        else getattr(part, "text", None)
                    )
                    if isinstance(text, str) and text:
                        texts.append(text)
            content = getattr(parsed, "content", None)
            reasoning = getattr(parsed, "reasoning_content", None)
            if texts:
                parsed.reasoning_content = "".join(texts)
            elif isinstance(reasoning, str) and reasoning == content:
                # No reasoning item at all (effort="none"): whatever agno put
                # here is the echo. The visible answer is never reasoning.
                parsed.reasoning_content = None
            return parsed

        def _parse_provider_response_delta(
            self, stream_event, assistant_message, tool_use
        ):
            """Map DeepSeek's streamed reasoning, which agno has no branch for.

            DeepSeek streams chain-of-thought as ``response.reasoning_text.delta``
            (measured: 177 deltas on one ``effort="max"`` turn). agno handles only
            ``response.reasoning_summary_text.delta``, so every one of those was
            dropped and a reasoning turn streamed no reasoning at all.
            """
            if getattr(stream_event, "type", None) == "response.reasoning_text.delta":
                from agno.models.response import ModelResponse

                delta = getattr(stream_event, "delta", None)
                model_response = ModelResponse()
                if isinstance(delta, str) and delta:
                    model_response.reasoning_content = delta
                return model_response, tool_use
            return super()._parse_provider_response_delta(
                stream_event, assistant_message, tool_use
            )

    return CompatibleDeepSeekResponses


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


def _anthropic_thinking(
    model: str, *, reasoning: bool
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return the ``(thinking, output_config)`` pair for a bare Claude id.

    Anthropic has the same hazard as Gemini -- an unset thinking config is
    "provider decides", not "off" -- but the default differs by generation:
    omitting ``thinking`` runs ADAPTIVE on Sonnet 5 and Opus 5, and runs
    without thinking on Opus 4.8/4.7 and everything older. Since
    ``Settings.mid_model`` defaults to ``claude-sonnet-5``, leaving it unset
    silently bought thinking on every non-reasoning agent -- and because
    thinking shares the ``max_tokens`` budget with the response text, that
    truncated large structured outputs into the unparsed-``str`` failure
    ``expect_schema`` exists to diagnose. So bound it explicitly.
    """
    if reasoning:
        return {"type": "adaptive"}, {"effort": "high"}
    folded = model.casefold()
    if folded.startswith(_ANTHROPIC_ALWAYS_THINKING):
        # Fable/Mythos reject an explicit disabled config; only max_tokens bounds it.
        return None, None
    version = anthropic_version(model)
    if version is None or version < _ANTHROPIC_MODERN:
        # Pre-4.6 ids: omitting the config already means no thinking on that
        # generation, so there is nothing to bound -- and agno rejects a thinking
        # config on the Haiku 3/3.5 families outright.
        return None, None
    # Accepted on Sonnet 5, Opus 4.8/4.7/4.6 and Sonnet 4.6. On Opus 5 it is
    # accepted only at effort `high` or below -- we send no `output_config` here,
    # and the default effort is `high`, so this stays inside that limit.
    return {"type": "disabled"}, None


def _anthropic_max_tokens(model: str, *, reasoning: bool) -> int:
    """Bound Claude's output budget instead of inheriting agno's 8192 default.

    ``max_tokens`` caps thinking PLUS response text, so 8192 is shared between a
    reasoning budget and the full JSON body -- enough to truncate a
    ``ResumeContent`` or starve a scout's web-search tool loop, both of which
    surface as an unparsed ``str`` rather than an HTTP error. These calls are
    non-streaming, so stay near the SDK's ~16000 non-streaming guidance rather
    than the models' 128K ceiling, and honor the per-model non-streaming ceiling
    the SDK enforces (Opus 4/4.1 only) so a custom id cannot raise ValueError.
    """
    want = 32000 if reasoning else 16000
    try:
        from anthropic._constants import MODEL_NONSTREAMING_TOKENS
    except ImportError:  # pragma: no cover - private SDK constant
        return want
    ceiling = MODEL_NONSTREAMING_TOKENS.get(model)
    return min(want, ceiling) if ceiling else want


def _configured_model_option(model_id: str, suffix: str) -> str | None:
    """Resolve per-tier tuning for ``model_id`` from effective settings."""
    settings = get_settings()
    for tier in ("premium", "mid", "cheap"):
        if getattr(settings, f"{tier}_model", None) == model_id:
            value = getattr(settings, f"{tier}_{suffix}", None)
            if value:
                return str(value)
    return None


def _reasoning_effort_for(model_id: str, provider: str) -> str:
    configured = _configured_model_option(model_id, "reasoning_effort")
    entry = catalog_entry(model_id)
    if configured and entry and configured in entry.reasoning_efforts:
        return configured
    return "max" if provider == "deepseek" else "high"


_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _responses_effort(model_id: str, provider: str, *, reasoning: bool) -> str | None:
    """Resolve the explicit ``reasoning.effort`` for a catalogued Responses model.

    Shared by OpenAI and DeepSeek because both speak the Responses API. For
    DeepSeek this single value is also the thinking **toggle**: its lowest
    declared effort is ``none``, which is how a non-reasoning agent turns
    thinking off. An uncatalogued id returns ``None`` so no reasoning config is
    sent at all -- its effort vocabulary is unknown.
    """
    entry = catalog_entry(model_id)
    if entry is None or not entry.reasoning_efforts:
        return None
    if not reasoning:
        return min(entry.reasoning_efforts, key=_EFFORT_ORDER.index)

    selected = _reasoning_effort_for(model_id, provider)
    if selected in entry.reasoning_efforts:
        return selected
    target = _EFFORT_ORDER.index(selected)
    return min(
        entry.reasoning_efforts,
        key=lambda effort: (
            abs(_EFFORT_ORDER.index(effort) - target),
            _EFFORT_ORDER.index(effort),
        ),
    )


def _openai_max_output_tokens(*, reasoning: bool) -> int:
    """Leave room for visible output after Responses API reasoning tokens.

    Deliberately not ``_anthropic_max_tokens``' number. That one sits near
    16000 because the Anthropic SDK enforces a per-model non-streaming ceiling
    (``MODEL_NONSTREAMING_TOKENS``) and raises above it -- a real constraint.
    The Responses API has no equivalent, and copying the figure across rationed
    output the model was willing to produce: a large structured response
    stopped at ``incomplete_details.reason="max_output_tokens"`` mid-string,
    and a body truncated that way parses as nothing, so the whole call was paid
    for and yielded zero. Being stingy here is a false economy; the ceiling's
    job is to bound a runaway, not to budget legitimate output.

    The reasoning figure is the larger one because on OpenAI -- unlike
    Anthropic, where ``thinking`` has its own budget -- reasoning tokens are
    spent out of this same allowance, so the same visible answer needs more.
    """
    return 64000 if reasoning else 32000


def _build_openai_responses(
    model_id: str, *, api_key: str | None, reasoning: bool
) -> Any:
    """Build an OpenAI model with the shared Responses request policy."""
    OpenAIResponses = _compatible_openai_responses_class()
    effort = _responses_effort(model_id, "openai", reasoning=reasoning)
    return OpenAIResponses(
        id=split_provider(model_id)[1],
        api_key=api_key,
        # Agno's reasoning_effort Literal omits valid Responses values.
        reasoning={"effort": effort} if effort is not None else None,
        # Ask for a summary whenever a reasoning config is sent, including at
        # effort "none". Agno's Responses adapter treats "reasoning requested
        # but no summary requested" as "the visible output text *is* the
        # reasoning" and copies every output_text delta into reasoning_content.
        # Because a catalogued id always carries an explicit effort, that fired
        # on every OpenAI agent: the reply was duplicated into the reasoning
        # channel token by token, alternating the two event kinds on each delta
        # so the chat rendered one disclosure and one markdown block per token.
        # Verified live on gpt-5.6-terra -- accepted at every effort, drops the
        # duplication to zero, and a real reasoning call streams genuine
        # summaries (752 reasoning tokens) instead of an echo of its answer.
        # An uncatalogued id sends no reasoning config, so it asks for nothing.
        reasoning_summary="auto" if effort is not None else None,
        max_output_tokens=_openai_max_output_tokens(reasoning=reasoning),
        # Agno requests encrypted reasoning for stateless tool-call replay.
        store=False,
    )


def _build_deepseek_responses(
    model_id: str, *, api_key: str | None, reasoning: bool
) -> Any:
    """Build a DeepSeek model on the Responses API.

    DeepSeek is the fourth provider with the "unset means provider decides"
    trap, and on Responses the fix is a first-class parameter rather than the
    ``extra_body={"thinking": {"type": "disabled"}}`` side-channel the Chat
    Completions adapter needed: ``reasoning.effort`` is *both* the toggle and
    the dial, and ``none`` disables thinking. Verified live -- omitting
    ``reasoning`` entirely spent 46 reasoning tokens, ``effort="none"`` spends
    zero and emits no reasoning output item at all.
    """
    DeepSeekResponses = _compatible_deepseek_responses_class()
    effort = _responses_effort(model_id, "deepseek", reasoning=reasoning)
    return DeepSeekResponses(
        id=split_provider(model_id)[1],
        api_key=api_key,
        reasoning={"effort": effort} if effort is not None else None,
        # Same rule as OpenAI: whenever a reasoning config is sent, ask for a
        # summary, or agno's streaming branch relabels every visible output_text
        # delta as reasoning. DeepSeek accepts the field and never generates a
        # summary (verified: `summary` is always `[]`), which is exactly why the
        # non-streaming echo needs its own override in the model class.
        reasoning_summary="auto" if effort is not None else None,
        max_output_tokens=_openai_max_output_tokens(reasoning=reasoning),
        # Documented as unsupported and always reported back as false. Sent
        # anyway so the value we ask for matches the value we get.
        store=False,
    )


def _gemini_interactions_thinking_level_for(
    model_id: str, provider: str
) -> GeminiInteractionsThinkingLevel:
    """Return a Gemini Interactions-compatible thinking level."""
    effort = _reasoning_effort_for(model_id, provider)
    if effort == "minimal":
        return "minimal"
    if effort == "low":
        return "low"
    if effort == "medium":
        return "medium"
    return "high"


def prompt_cache_for(model_id: str, *, settings: Settings | None = None) -> bool:
    """Whether this agent should ask its provider to cache its system block.

    The one switch (``Settings.prompt_cache_enabled``) crossed with what the
    provider can actually do. Every agent that runs N times per run should pass
    this to ``build_model``: the instruction block is identical across those N
    calls, so paying full price for it N times is pure waste.

    Note this caches the *system* block, not turn messages — see the
    ``cache_system_prompt`` note in the root CLAUDE.md. Per-job context in a
    user message is not covered, which is why a run-constant document belongs
    in the system block rather than in the per-call prompt.
    """
    if not (settings or get_settings()).prompt_cache_enabled:
        return False
    return provider_capabilities(model_id).supports_prompt_cache


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
    reasoning_effort = _reasoning_effort_for(model_id, provider) if reasoning else None
    key = api_key or resolve_api_key(model_id) or None
    if provider == "openai":
        return _build_openai_responses(model_id, api_key=key, reasoning=reasoning)
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
                thinking_level=reasoning_effort if reasoning else "low",
            )
        # Pre-3 ids have no thinking_level at all -- sending one is the mirror
        # image of the thinking_budget-on-Gemini-3 failure, and agno forwards any
        # non-None value straight into ThinkingConfig -- so 0 is the only way off
        # here, and reasoning is left to the provider's own budget.
        return Gemini(
            id=model,
            api_key=key,
            thinking_budget=None if reasoning else 0,
        )
    if provider == "deepseek":
        return _build_deepseek_responses(model_id, api_key=key, reasoning=reasoning)
    from agno.models.anthropic import Claude

    thinking, output_config = _anthropic_thinking(model, reasoning=reasoning)
    if output_config is not None and reasoning_effort is not None:
        output_config = {"effort": reasoning_effort}
    return Claude(
        id=model,
        api_key=key,
        cache_system_prompt=cache_system_prompt,
        max_tokens=_anthropic_max_tokens(model, reasoning=reasoning),
        thinking=thinking,
        output_config=output_config,
    )


def build_search_equipped(
    model_id: str,
    mode: SearchMode | None = None,
    *,
    reasoning: bool = False,
    cache_system_prompt: bool = False,
    tool_search: Any | None = None,
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
        return (
            _build_openai_responses(model_id, api_key=api_key, reasoning=reasoning),
            [OPENAI_WEB_SEARCH_TOOL],
        )
    if plan.strategy == "native_deepseek":
        return (
            _build_deepseek_responses(model_id, api_key=api_key, reasoning=reasoning),
            [DEEPSEEK_WEB_SEARCH_TOOL],
        )
    if plan.strategy == "native_gemini":
        from agno.models.google.gemini_interactions import GeminiInteractions

        # Same "unset means provider decides" rule `build_model` guards: leaving
        # thinking_level unset buys an unbounded automatic budget, so a
        # non-reasoning research agent bounds it at "low" rather than omitting
        # it - but only on Gemini 3, which is the only generation that accepts
        # thinking_level at all. A pre-3 id (e.g. a custom gemini-2.5-* advisor
        # model) has no thinking_level and mirrors the `build_model` guard by
        # omitting it, leaving reasoning to the provider's own budget.
        kwargs: dict[str, Any] = {
            "id": model_name,
            "api_key": api_key,
            "search": True,
            "store": False,
        }
        if model_name.casefold().startswith("gemini-3"):
            kwargs["thinking_level"] = (
                _gemini_interactions_thinking_level_for(model_id, plan.provider)
                if reasoning
                else "low"
            )
        return (GeminiInteractions(**kwargs), [])

    model = build_model(
        model_id,
        api_key=api_key,
        cache_system_prompt=cache_system_prompt,
        reasoning=reasoning,
    )
    if plan.strategy == "native_anthropic":
        return model, [anthropic_web_search_tool(model_id)]
    if plan.strategy == "tool":
        if tool_search is not None:
            return model, [tool_search]
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
    from resume_agent.tenancy.limits import enforce_agent_budget

    enforce_agent_budget(
        SimpleNamespace(model=SimpleNamespace(id=model, provider=provider))
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
        usage = getattr(response, "usage_metadata", None)
        from resume_agent.tenancy.costs import MeteredUsage
        from resume_agent.tenancy.usage import record_direct_usage

        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        record_direct_usage(
            MeteredUsage(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=int(
                    getattr(usage, "cached_content_token_count", 0) or 0
                ),
                reasoning_tokens=int(getattr(usage, "thoughts_token_count", 0) or 0),
                audio_input_tokens=input_tokens,
                total_tokens=int(getattr(usage, "total_token_count", 0) or 0),
            )
        )
        return (response.text or "").strip()
    import io

    from openai import OpenAI

    client = OpenAI(api_key=key)
    buffer = io.BytesIO(audio)
    buffer.name = _OPENAI_AUDIO_NAMES.get(mime_type, "audio.webm")
    result = client.audio.transcriptions.create(model=model, file=buffer)
    usage = getattr(result, "usage", None)
    from resume_agent.tenancy.costs import MeteredUsage
    from resume_agent.tenancy.usage import record_direct_usage

    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    record_direct_usage(
        MeteredUsage(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            audio_input_tokens=input_tokens,
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
    )
    return result.text.strip()
