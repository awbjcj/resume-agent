"""Structured-output turn helpers shared by the coach and interviewer stacks."""

from __future__ import annotations

import logging
import re

from resume_agent.config import get_settings
from resume_agent.llm_runner import expect_schema, expect_text
from resume_agent.sessions.stream import (
    Completed,
    Failed,
    StreamSink,
    TextDelta,
)

logger = logging.getLogger(__name__)

DELIMITER = "---METADATA---"

# A model that bolds the sentinel, pads it, or draws longer rules is still
# emitting it, and reading those as prose dumps the formatter payload into the
# chat window. The METADATA token is mandatory: DeepSeek writes a bare `---`
# horizontal rule as a section break between the agenda and its question, so
# matching the rules alone would truncate a reply mid-turn.
_MARKER = re.compile(
    r"[*_`~ \t]{0,4}-{3,6}[ \t]{0,2}METADATA[ \t]{0,2}-{3,6}[*_`~ \t]{0,4}",
    re.IGNORECASE,
)
# The longest string _MARKER can match. The emitter must hold back at least
# this much, or a marker split across deltas gets flushed as prose before the
# rest of it arrives.
MARKER_MAX_LEN = 4 + 6 + 2 + len("METADATA") + 2 + 6 + 4


class ProseEmitter:
    """Expose prose while retaining the complete persona output for formatting."""

    def __init__(self, sink: StreamSink, holdback: int = 32) -> None:
        self._sink = sink
        self._holdback = max(holdback, MARKER_MAX_LEN + 2)
        self._raw: list[str] = []
        self._prose: list[str] = []
        self._pending = ""
        self._marker_found = False
        self._finished = False

    def feed(self, text: str) -> None:
        if self._finished:
            return
        self._raw.append(text)
        if self._marker_found:
            return
        self._pending += text
        marker = _MARKER.search(self._pending)
        if marker is not None:
            visible = self._pending[: marker.start()]
            if visible.endswith("\r\n"):
                visible = visible[:-2]
            elif visible.endswith("\n"):
                visible = visible[:-1]
            self._flush(visible)
            self._pending = ""
            self._marker_found = True
            return
        safe_length = len(self._pending) - self._holdback
        if safe_length > 0:
            self._flush(self._pending[:safe_length])
            self._pending = self._pending[safe_length:]

    def _flush(self, text: str) -> None:
        if not text:
            return
        self._prose.append(text)
        self._sink.emit(TextDelta(text))

    @property
    def marker_found(self) -> bool:
        return self._marker_found

    def finish(self) -> tuple[str, str]:
        if not self._finished:
            if not self._marker_found:
                self._flush(self._pending)
            self._pending = ""
            self._finished = True
        return "".join(self._prose), "".join(self._raw)


class StreamFailed(RuntimeError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def persona_output(
    agent,
    prompt: str,
    sink: StreamSink,
    reporter,
    *,
    source: str,
) -> tuple[str, str]:
    """Return visible prose and complete notes without forwarding terminals."""
    stream = getattr(agent, "stream", None)
    if not get_settings().stream_enabled or stream is None:
        return "", expect_text(agent.run(prompt), source=source)

    emitter = ProseEmitter(sink)
    final_response = None
    for event in stream(prompt):
        reporter.checkpoint()
        if isinstance(event, TextDelta):
            emitter.feed(event.text)
        elif isinstance(event, Completed):
            final_response = event.response
        elif isinstance(event, Failed):
            raise StreamFailed(event.message, event.code)
        else:
            sink.emit(event)
    if final_response is None:
        raise StreamFailed("The model stream ended without a final response.", "STREAM_ERROR")
    prose, streamed_output = emitter.finish()
    if streamed_output and not emitter.marker_found:
        # Emitting the sentinel is a model behaviour, not an invariant we
        # control. DeepSeek v4 omits it on every coach turn -- verified against
        # the live prompt with thinking both on and off, while Claude honours
        # it -- and the run completes normally, so there is nothing to retry.
        # The formatter is an LLM that extracts the turn from raw notes either
        # way, so failing here would cost the user their whole answer and buy
        # nothing. Degrade: the entire response becomes both the visible reply
        # and the formatter's input.
        logger.warning(
            "%s omitted the %s delimiter (%d chars); treating the whole "
            "response as both prose and formatter notes",
            source,
            DELIMITER,
            len(streamed_output),
        )
    full_output = streamed_output or expect_text(final_response, source=source)
    return prose, full_output


class TurnRejected(ValueError):
    """A formatted turn failed validation against the session's rules."""

    def __init__(self, message: str, *, fallback_text: str = "") -> None:
        super().__init__(message)
        self.fallback_text = fallback_text


class DraftRejected(TurnRejected):
    """A draft note failed its content or verbatim-quote integrity gate."""


def format_with_retry(formatter, notes: object, schema, validate, *, label: str):
    """Format untrusted notes into ``schema`` and validate, retrying once.

    The retry feeds the rejection reason back to the formatter; a second
    rejection propagates. Non-``schema`` output raises ``UnparsedAgentOutput``
    (a TypeError) immediately, carrying the model, provider, token counts, and a
    response head/tail -- this seam is shared by the coach and interview stacks,
    so a truncated or rejected turn is diagnosable in both without a redeploy.
    """
    prompt = f"{label} (UNTRUSTED):\n{notes}"
    formatted = expect_schema(formatter.run(prompt), schema, source=label)
    try:
        return validate(formatted, True)
    except TurnRejected as first:
        result = formatter.run(f"{prompt}\n\nPREVIOUS OUTPUT REJECTED: {first}")
        try:
            retry = expect_schema(result, schema, source=f"{label} retry")
        except TypeError as exc:
            raise exc from first
        try:
            return validate(retry, False)
        except TurnRejected as second:
            second.fallback_text = str(getattr(retry, "message", "") or "")
            raise
