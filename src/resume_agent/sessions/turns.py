"""Structured-output turn helpers shared by the coach and interviewer stacks."""

from __future__ import annotations

from resume_agent.config import get_settings
from resume_agent.llm_runner import expect_schema, expect_text
from resume_agent.sessions.stream import (
    Completed,
    Failed,
    StreamSink,
    TextDelta,
)

DELIMITER = "---METADATA---"


class ProseEmitter:
    """Expose prose while retaining the complete persona output for formatting."""

    def __init__(self, sink: StreamSink, holdback: int = 32) -> None:
        self._sink = sink
        self._holdback = max(holdback, len(DELIMITER) + 2)
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
        marker_at = self._pending.find(DELIMITER)
        if marker_at >= 0:
            visible = self._pending[:marker_at]
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
        raise StreamFailed(
            f"The {source} response did not include the required {DELIMITER} delimiter.",
            "MISSING_DELIMITER",
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
