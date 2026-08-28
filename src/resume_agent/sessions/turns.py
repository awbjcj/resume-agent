"""Structured-output turn helpers shared by the coach and interviewer stacks."""

from __future__ import annotations

import logging
import re

from resume_agent.config import get_settings
from resume_agent.llm_runner import expect_schema, expect_text
from resume_agent.sessions.stream import (
    Completed,
    Failed,
    Settled,
    StreamSink,
    TextDelta,
)

logger = logging.getLogger(__name__)

DELIMITER = "---METADATA---"

_MARKER_DECORATION = r"[*_`~ \t]"

# A model that bolds the sentinel, pads it, or draws longer rules is still
# emitting it, and reading those as prose dumps the formatter payload into the
# chat window. The METADATA token is mandatory: DeepSeek writes a bare `---`
# horizontal rule as a section break between the agenda and its question, so
# matching the rules alone would truncate a reply mid-turn. A missing leading
# rule is accepted only when the trailing rule is still present; this covers
# the observed `METADATA---` provider deviation without treating a plain
# "Metadata" heading as a private boundary.
_MARKER = re.compile(
    rf"^{_MARKER_DECORATION}{{0,4}}(?:"
    rf"-{{3,6}}[ \t]{{0,2}}METADATA[ \t]{{0,2}}-{{3,6}}|"
    rf"METADATA[ \t]{{0,2}}-{{3,6}})"
    rf"{_MARKER_DECORATION}{{0,4}}[\\]?[ \t]*(?=\r?$)",
    re.IGNORECASE | re.MULTILINE,
)
# When the sentinel never arrives, the metadata block is its own boundary: it
# opens with one of the schemas' keys alone on a line. Without this the
# degradation rule below would dump `action:`/`topic_updates:`/`draft:` into
# the chat window, which is what it looked like on Gemini.
#
# The guard is deliberately narrow, because cutting a reply short is worse than
# the leak it prevents: the key must be bare, lowercase, at the start of a line,
# preceded by a blank line, and followed by a colon. A coach writes
# "**Action:** ..." or "the draft: ..." mid-sentence; it does not open a line
# with `research_actions:`.
_BLOCK_KEYS = (
    "action",
    "topic_id",
    "topic_updates",
    "draft",
    "draft_fields",
    "research_actions",
    "question_id",
    "follow_up",
    "hints",
    "plan",
)
_BLOCK_START = rf"\n[ \t]*\n(?=(?:{'|'.join(_BLOCK_KEYS)})[ \t]*:)"

# The Scout's metadata block is not `key: value` lines at all -- it is a table
# of `PROPOSE | company | ats | url | reason` rows -- so the key guard above
# never matched it and a model that skipped the sentinel printed the whole
# proposal table into the chat window. Same narrowness rule as the key guard:
# the verb must be uppercase, alone at the start of a line after a blank line,
# and immediately followed by the row's first pipe, so prose that merely
# contains "propose" or a pipe is untouched.
_ROW_VERBS = ("PROPOSE", "AVOID")
_ROW_START = rf"\n[ \t]*\n(?=(?:{'|'.join(_ROW_VERBS)})[ \t]*\|)"

# Case-sensitive on its own: the row verbs are a deliberate uppercase shape,
# and folding them would cut a reply at a sentence starting with "Avoid ...".
_BOUNDARY = re.compile(
    f"(?im:{_MARKER.pattern}|{_BLOCK_START})|{_ROW_START}",
)

# The longest string the boundary can match. The emitter must hold back at
# least this much, or a boundary split across deltas gets flushed as prose
# before the rest of it arrives -- the lookahead counts, because the key has to
# be in the buffer for the blank line before it to match.
MARKER_MAX_LEN = max(
    4 + 6 + 2 + len("METADATA") + 2 + 6 + 4,
    2 + max(len(key) for key in _BLOCK_KEYS) + 1,
    2 + max(len(verb) for verb in _ROW_VERBS) + 1,
)

_MARKER_PREFIX = re.compile(
    rf"(?:{_MARKER_DECORATION}{{0,4}}|"
    rf"{_MARKER_DECORATION}{{0,4}}-{{1,6}}|"
    rf"{_MARKER_DECORATION}{{0,4}}-{{3,6}}[ \t]{{0,2}}(?:M|ME|MET|META|METAD|METADA|METADAT|METADATA)?|"
    rf"{_MARKER_DECORATION}{{0,4}}-{{3,6}}[ \t]{{0,2}}METADATA[ \t]{{0,2}}-{{0,6}}{_MARKER_DECORATION}{{0,4}}|"
    rf"{_MARKER_DECORATION}{{0,4}}(?:M|ME|MET|META|METAD|METADA|METADAT|METADATA[ \t]{{0,2}}-{{0,6}}){_MARKER_DECORATION}{{0,4}}[\\]?)\Z",
    re.IGNORECASE,
)


def _could_complete_block_boundary(value: str) -> bool:
    if not value.startswith("\n"):
        return False
    rest = value[1:].lstrip(" \t")
    if not rest:
        return True
    if not rest.startswith("\n"):
        return False
    rest = rest[1:].lstrip(" \t")
    if not rest:
        return True
    folded = rest.casefold()
    for key in _BLOCK_KEYS:
        if key.startswith(folded) or (
            folded.startswith(key) and not folded[len(key) :].strip(" \t")
        ):
            return True
    for verb in _ROW_VERBS:
        if verb.startswith(rest) or (
            rest.startswith(verb) and not rest[len(verb) :].strip(" \t")
        ):
            return True
    return False


def _safe_prefix_len(pending: str) -> int:
    """Return the prose prefix that cannot still grow into a boundary."""
    start = max(0, len(pending) - MARKER_MAX_LEN)
    for index in range(start, len(pending)):
        suffix = pending[index:]
        if _MARKER_PREFIX.fullmatch(suffix):
            while index > start and pending[index - 1] in "\r\n":
                index -= 1
            return index
        if _could_complete_block_boundary(suffix):
            return index
    return len(pending)


def user_visible_prose(text: str) -> str:
    """Remove persona formatter payloads from text that may reach the UI."""
    boundary = _BOUNDARY.search(text)
    if boundary is None:
        return text
    return text[: boundary.start()].rstrip("\r\n")


class ProseEmitter:
    """Expose prose while retaining the complete persona output for formatting."""

    def __init__(self, sink: StreamSink) -> None:
        self._sink = sink
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
        marker = _BOUNDARY.search(self._pending)
        if marker is not None:
            visible = user_visible_prose(self._pending)
            self._flush(visible)
            self._pending = ""
            self._marker_found = True
            return
        safe_length = _safe_prefix_len(self._pending)
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
        raise StreamFailed(
            "The model stream ended without a final response.", "STREAM_ERROR"
        )
    prose, streamed_output = emitter.finish()
    if prose:
        sink.emit(Settled())
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
            "%s emitted neither the %s delimiter nor a metadata block (%d "
            "chars); treating the whole response as both prose and formatter "
            "notes",
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
