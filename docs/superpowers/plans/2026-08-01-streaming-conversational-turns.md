# Streaming Conversational Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream the Profile Coach's and Mock Interviewer's replies token-by-token with live tool activity, a working stop button, and a validation split so one bad draft quote no longer destroys the whole turn.

**Architecture:** `AgentRunner` gains a `stream()` method that yields our own `StreamEvent` dataclasses (never agno types). Turn services feed those events into a `StreamSink` — an append-only ndjson file per run for the API, stdout for the CLI. A new SSE route tails that file from a client-supplied offset so a mid-turn refresh resumes instead of losing the answer. The persona agent writes user-facing prose followed by a `---METADATA---` block; prose streams, metadata is buffered, and the existing formatter still projects structure from the complete output.

**Tech Stack:** Python 3.12 · FastAPI · sse-starlette · agno 2.8.2 · pytest · React 19 · TanStack Query · Vitest · Base UI/shadcn

## Global Constraints

- **Branch:** `docs/streaming-conversational-turns` (already exists, off `origin/main`). There is no `dev` branch in this clone.
- **Tests run offline.** No API key, no network, no browser. Every agent is faked.
- Python tests: `.venv/Scripts/python.exe -m pytest`. Lint: `ruff check`.
- Web tests: `cd web && npm test`. Lint: `cd web && npm run lint`.
- **Never import a provider SDK outside `build_model`.** `stream()` maps agno events to our dataclasses; nothing downstream sees an agno type.
- **`enforce_agent_budget` runs before the first provider call** in every path, streaming included. Quota and shared-key gating are not to be weakened.
- **Fact-lock is unchanged.** `approve_draft` remains the only path into the corpus and still requires a draft that passed the verbatim-quote gate.
- Verified agno 2.8.2 facts (do not re-derive): `Agent.run(input, stream=, stream_events=, yield_run_output=)`; `RunEvent` values include `RunContent`, `ToolCallStarted`, `ToolCallCompleted`, `ToolCallError`, `ReasoningContentDelta`, `RunCompleted`, `RunError`, `RunCancelled`; `RunContentEvent` has `.content` and `.reasoning_content`; `ToolCall*Event` has `.tool` with `.tool_name`, `.tool_args`, `.result`, `.tool_call_error`; `RunErrorEvent` has `.content` and `.error_type`; `RunCancelledEvent` has `.reason`.
- **Delimiter:** the literal string `---METADATA---`. Holdback window: 32 characters.
- Regenerate contracts with `bash scripts/gen_ts_client.sh` whenever a route or schema changes; `tests/api/test_openapi_contract.py` is the drift gate.

## Correctness Amendments (authoritative over task snippets)

The plan was reviewed against the design, the current branch, and pinned Agno
2.8.2 before implementation. The following amendments fix lifecycle and contract
bugs in the draft snippets; implementation and tests must follow these rules even
where a later task says to apply a snippet "verbatim":

- Normalize Agno event tags with `event.value` (falling back to a raw string),
  never `str(event)`. Use faithful enum-shaped tests. Carry the final `RunOutput`
  on the internal `Completed(response)` event instead of mutable
  `AgentRunner.last_output` state.
- Add `call_id` to `ToolStarted` and `ToolCompleted`, encode it as `callId`, and
  match tool completion in the web reducer by id rather than by display name.
- `AgentRunner.stream()` may yield an internal `Completed`/`Failed`, but
  `persona_output` consumes rather than forwards that terminal. The router's
  stream-work wrapper emits exactly one wire terminal: `Completed` only after
  the service has formatted, validated, and durably stored the turn; `Failed`
  for every exception or cancellation. Notices are emitted before `Completed`.
- A provider failure after partial prose raises before any durable mutation.
  Partial turns are never formatted or stored. The in-place retry owns recovery.
- Pass the run reporter into `persona_output` and call `reporter.checkpoint()`
  for every provider event before showing it. Stop therefore discards the
  synthetic parts and the worker raises `RunCancelled` before session mutation.
- Make sink close idempotent and terminal-aware. Validate decoded NDJSON shapes,
  reject malformed indexes/payloads, and ignore writes after a terminal. Remove
  stream siblings from `RunManager.clear()` and `sweep()`.
- The SSE grace fallback preserves truth: `done -> completed`;
  `error/cancelled -> failed` with the run error/error code. Validate `offset`
  as a non-negative query parameter. Replace the hanging "empty live stream"
  route test with a generator test that observes an empty poll and then an event.
- Only note-content/quote integrity checks raise `DraftRejected`. Topic state,
  duplicate draft, update, agenda, and action errors remain structural and may
  not be silently converted into a dropped draft.
- The interview stack has no draft subtype. Its lenient validator parameter is
  accepted for the shared formatter contract but structural failures still
  raise; after two failures its service stores streamed prose against the
  currently asked question with a durable notice and does not advance the plan.
- Parse SSE JSON into a validated `StreamEvent` at the browser boundary. Unknown
  or malformed payloads do not advance the offset. Reset parts, cursor, errors,
  and reconnect timers on every `runId` change.
- Conversation launches include run metadata (`sessionId` when available).
  Pages combine the just-launched id with the existing rehydrated run store, so
  refresh can reconstruct a live stream and interview pages cannot attach to a
  different session's run.
- Stop clears partial parts/run state immediately after requesting cooperative
  cancellation. Retry clears the failed partial before launching a fresh run.
  Busy state covers both POST launch and streaming, preventing duplicate sends.
- Capture the durable turn count when a run is attached. Hide the synthetic
  bubble synchronously once that count advances; reset it afterward. Do not use
  the unused `pendingRun` state from Task 11's draft snippet.
- Preserve each coach turn's existing `ResearchActionCard` content adjacent to
  that message, and leave draft/recap/impact/debrief surfaces intact. The shared
  chat components use the repository's established visual tokens, add an
  `aria-live` transcript status, accessible tool states, keyboard operation, and
  responsive widths rather than introducing a new visual language.
- Intermediate verification stays focused as requested. Contract regeneration
  happens once after backend/schema/route work is coherent, followed by the
  final whole-repository verification matrix.

---

## File Structure

**Create:**

| Path                                              | Responsibility                                                                 |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| `src/resume_tailor_harness/sessions/stream.py`             | `StreamEvent` types, ndjson codec, `StreamSink` protocol + three sinks, reader |
| `src/resume_tailor_harness/api/runs/stream_sse.py`         | Async generator tailing a run's ndjson from an offset                          |
| `tests/test_sessions_stream.py`                   | Codec, sinks, reader, offset resume                                            |
| `tests/test_llm_runner_stream.py`                 | `AgentRunner.stream` event mapping + retry policy                              |
| `tests/test_turn_prose.py`                        | `ProseEmitter` delimiter handling                                              |
| `tests/api/test_run_stream_route.py`              | SSE route auth, offset, terminal close                                         |
| `web/src/lib/chat/events.ts`                      | TS `StreamEvent` union (hand-written; SSE bodies are not in OpenAPI)           |
| `web/src/lib/chat/useChatStream.ts`               | EventSource + offset resume → `parts[]`                                        |
| `web/src/lib/chat/events.test.ts`                 | Python↔TS tag parity                                                           |
| `web/src/lib/chat/useChatStream.test.ts`          | Reducer + resume behavior                                                      |
| `web/src/components/chat/ChatThread.tsx`          | Scroll anchoring + jump-to-latest                                              |
| `web/src/components/chat/ChatMessage.tsx`         | Role bubble, renders parts in arrival order                                    |
| `web/src/components/chat/parts/TextPart.tsx`      | Streaming markdown + caret                                                     |
| `web/src/components/chat/parts/ToolPart.tsx`      | Collapsible activity chip                                                      |
| `web/src/components/chat/parts/ReasoningPart.tsx` | Collapsed disclosure                                                           |
| `web/src/components/chat/parts/NoticePart.tsx`    | Degradation notice                                                             |
| `web/src/components/chat/ChatComposer.tsx`        | Textarea, send/stop, transcribe                                                |
| `web/src/components/chat/ChatThread.test.tsx`     | Anchoring, pill, part order                                                    |

**Modify:**

| Path                                                       | Change                                                                               |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `src/resume_tailor_harness/llm_runner.py`                           | `StreamEvent` re-export, `AgentRunner.stream()`                                      |
| `src/resume_tailor_harness/sessions/turns.py`                       | `DraftRejected`, `ProseEmitter`, `format_with_retry` strict/lenient                  |
| `src/resume_tailor_harness/profile/coach.py`                        | Metadata contract in instructions; `normalize_*` strict flag; `ValidatedTurn.notice` |
| `src/resume_tailor_harness/profile/coach_store.py`                  | `CoachTurnRecord.notice`                                                             |
| `src/resume_tailor_harness/services/profile_coach.py`               | `sink=` parameter; stream the coach agent                                            |
| `src/resume_tailor_harness/interview/agent.py`                      | Same treatment as coach                                                              |
| `src/resume_tailor_harness/interview/store.py`                      | `InterviewTurnRecord.notice`                                                         |
| `src/resume_tailor_harness/services/mock_interview.py`              | `sink=` parameter; stream the interviewer                                            |
| `src/resume_tailor_harness/api/runs/manager.py`                     | `stream_path(run_id)` accessor                                                       |
| `src/resume_tailor_harness/api/routers/runs.py`                     | `GET /runs/{run_id}/stream`                                                          |
| `src/resume_tailor_harness/api/routers/coach.py`, `interview.py`    | Pass `RunStreamSink` into the worker                                                 |
| `src/resume_tailor_harness/api/schemas/coach.py`, `interview.py`    | `notice` on turn schemas                                                             |
| `src/resume_tailor_harness/config.py`                               | `stream_enabled: bool = True`                                                        |
| `src/resume_tailor_harness/cli.py`                                  | `ConsoleStreamSink` for `profile coach`                                              |
| `web/src/features/coach/*`, `web/src/features/interview/*` | Refactor onto `<ChatThread>`                                                         |

---

## Task 1: Stream events, codec, and sinks

**Files:**

- Create: `src/resume_tailor_harness/sessions/stream.py`
- Test: `tests/test_sessions_stream.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `TextDelta(text)`, `ReasoningDelta(text)`, `ToolStarted(name, args_preview)`, `ToolCompleted(name, result_preview, ok)`, `Notice(message)`, `Completed()`, `Failed(message, code)`; `StreamSink` protocol with `emit(event)` and `close()`; `NullSink()`, `ConsoleStreamSink(write)`, `RunStreamSink(path, flush_interval=0.08, flush_chars=240)`; `encode_event(index, event) -> str`; `read_stream(path, offset=0) -> Iterator[tuple[int, str, dict]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sessions_stream.py
import json

from resume_tailor_harness.sessions.stream import (
    Completed,
    ConsoleStreamSink,
    Failed,
    Notice,
    NullSink,
    ReasoningDelta,
    RunStreamSink,
    TextDelta,
    ToolCompleted,
    ToolStarted,
    encode_event,
    read_stream,
)


def test_encode_event_carries_index_tag_and_payload():
    line = encode_event(3, TextDelta("hi"))
    assert json.loads(line) == {"i": 3, "t": "text", "v": {"text": "hi"}}


def test_tool_events_encode_their_previews():
    started = json.loads(encode_event(0, ToolStarted("search_corpus", "Kafka")))
    done = json.loads(encode_event(1, ToolCompleted("search_corpus", "3 hits", True)))
    assert started["v"] == {"name": "search_corpus", "argsPreview": "Kafka"}
    assert done["v"] == {"name": "search_corpus", "resultPreview": "3 hits", "ok": True}


def test_null_sink_discards_without_error():
    sink = NullSink()
    sink.emit(TextDelta("x"))
    sink.close()


def test_console_sink_writes_text_and_tool_chips():
    written: list[str] = []
    sink = ConsoleStreamSink(written.append)
    sink.emit(TextDelta("hello "))
    sink.emit(ToolStarted("search_corpus", "Kafka"))
    sink.emit(TextDelta("world"))
    sink.close()
    assert "hello " in written
    assert "world" in written
    assert any("search_corpus" in row for row in written)


def test_run_sink_round_trips_events_in_order(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1)
    sink.emit(TextDelta("a"))
    sink.emit(ToolStarted("t", "x"))
    sink.emit(TextDelta("b"))
    sink.emit(Completed())
    sink.close()
    rows = list(read_stream(path))
    assert [(index, tag) for index, tag, _ in rows] == [
        (0, "text"),
        (1, "tool_started"),
        (2, "text"),
        (3, "completed"),
    ]


def test_run_sink_coalesces_consecutive_text_deltas(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1000, flush_interval=1000)
    sink.emit(TextDelta("a"))
    sink.emit(TextDelta("b"))
    sink.emit(TextDelta("c"))
    sink.close()
    rows = list(read_stream(path))
    assert [(tag, payload) for _, tag, payload in rows] == [("text", {"text": "abc"})]


def test_non_text_event_flushes_pending_text_first(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1000, flush_interval=1000)
    sink.emit(TextDelta("a"))
    sink.emit(Notice("dropped"))
    sink.close()
    rows = list(read_stream(path))
    assert [tag for _, tag, _ in rows] == ["text", "notice"]


def test_read_stream_offset_returns_only_the_tail(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1)
    for letter in "abcd":
        sink.emit(TextDelta(letter))
    sink.close()
    rows = list(read_stream(path, offset=2))
    assert [index for index, _, _ in rows] == [2, 3]


def test_read_stream_missing_file_is_empty_not_an_error(tmp_path):
    assert list(read_stream(tmp_path / "absent.ndjson")) == []


def test_read_stream_skips_a_torn_trailing_line(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    path.write_text(encode_event(0, TextDelta("a")) + "\n{\"i\": 1, \"t\"", encoding="utf-8")
    assert [index for index, _, _ in read_stream(path)] == [0]


def test_failed_event_carries_message_and_code():
    payload = json.loads(encode_event(0, Failed("boom", "PROVIDER_ERROR")))
    assert payload["t"] == "failed"
    assert payload["v"] == {"message": "boom", "code": "PROVIDER_ERROR"}


def test_reasoning_event_tag():
    assert json.loads(encode_event(0, ReasoningDelta("why")))["t"] == "reasoning"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sessions_stream.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.sessions.stream'`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/sessions/stream.py
"""Streaming turn events, their ndjson wire form, and the sinks that carry them.

A conversational turn emits typed events as it runs. The API appends them to
``data/runs/{run_id}.stream.ndjson`` (append-only, tailed from an offset by SSE);
the CLI prints them; tests discard them. Nothing here imports a provider SDK --
``llm_runner`` maps agno's events onto these types so the rest of the codebase
never sees a third-party event class.

Appends deliberately do NOT use ``progress.atomic_write_text``. That function
truncates-and-replaces the whole file, which is right for a single JSON record
polled at 0.5s and catastrophic at one write per token.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TextDelta:
    """A chunk of user-facing prose."""

    text: str
    tag = "text"

    def payload(self) -> dict:
        return {"text": self.text}


@dataclass(frozen=True)
class ReasoningDelta:
    """A chunk of provider-exposed reasoning. Suppressed on the interview surface."""

    text: str
    tag = "reasoning"

    def payload(self) -> dict:
        return {"text": self.text}


@dataclass(frozen=True)
class ToolStarted:
    name: str
    args_preview: str = ""
    tag = "tool_started"

    def payload(self) -> dict:
        return {"name": self.name, "argsPreview": self.args_preview}


@dataclass(frozen=True)
class ToolCompleted:
    name: str
    result_preview: str = ""
    ok: bool = True
    tag = "tool_completed"

    def payload(self) -> dict:
        return {
            "name": self.name,
            "resultPreview": self.result_preview,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class Notice:
    """A degradation notice (for example, a draft note that failed its quote gate)."""

    message: str
    tag = "notice"

    def payload(self) -> dict:
        return {"message": self.message}


@dataclass(frozen=True)
class Completed:
    tag = "completed"

    def payload(self) -> dict:
        return {}


@dataclass(frozen=True)
class Failed:
    message: str
    code: str = "STREAM_ERROR"
    tag = "failed"

    def payload(self) -> dict:
        return {"message": self.message, "code": self.code}


StreamEvent = (
    TextDelta | ReasoningDelta | ToolStarted | ToolCompleted | Notice | Completed | Failed
)

#: Terminal tags. A reader stops once it sees one of these.
TERMINAL_TAGS = frozenset({"completed", "failed"})


def encode_event(index: int, event: StreamEvent) -> str:
    """Render one event as a single ndjson line (no trailing newline)."""
    return json.dumps(
        {"i": index, "t": event.tag, "v": event.payload()}, ensure_ascii=False
    )


class StreamSink(Protocol):
    """Where a turn's events go. Implementations must tolerate being closed twice."""

    def emit(self, event: StreamEvent) -> None: ...

    def close(self) -> None: ...


class NullSink:
    """Discards every event. Used by tests and by ``stream_enabled=false``."""

    def emit(self, event: StreamEvent) -> None:
        return None

    def close(self) -> None:
        return None


class ConsoleStreamSink:
    """Prints deltas and tool chips, for the CLI coach."""

    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write

    def emit(self, event: StreamEvent) -> None:
        if isinstance(event, TextDelta):
            self._write(event.text)
        elif isinstance(event, ToolStarted):
            self._write(f"\n  [{event.name} {event.args_preview}]\n")
        elif isinstance(event, Notice):
            self._write(f"\n  ! {event.message}\n")
        elif isinstance(event, Failed):
            self._write(f"\n  ! {event.message}\n")

    def close(self) -> None:
        self._write("\n")


class RunStreamSink:
    """Appends events as ndjson so an SSE reader can tail them from an offset.

    Consecutive :class:`TextDelta` events coalesce into one line until either
    ``flush_chars`` characters or ``flush_interval`` seconds have accumulated, so
    a fast model does not produce one syscall per token. Any non-text event
    flushes pending text first, which is what keeps arrival order intact.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        flush_interval: float = 0.08,
        flush_chars: int = 240,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._flush_interval = flush_interval
        self._flush_chars = flush_chars
        self._index = 0
        self._pending: list[str] = []
        self._pending_len = 0
        self._last_flush = time.monotonic()

    def emit(self, event: StreamEvent) -> None:
        if isinstance(event, TextDelta):
            self._pending.append(event.text)
            self._pending_len += len(event.text)
            due = time.monotonic() - self._last_flush >= self._flush_interval
            if self._pending_len >= self._flush_chars or due:
                self._flush_text()
            return
        self._flush_text()
        self._append(event)

    def _flush_text(self) -> None:
        if not self._pending:
            return
        text = "".join(self._pending)
        self._pending = []
        self._pending_len = 0
        self._last_flush = time.monotonic()
        self._append(TextDelta(text))

    def _append(self, event: StreamEvent) -> None:
        line = encode_event(self._index, event)
        self._index += 1
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()

    def close(self) -> None:
        self._flush_text()


def read_stream(path: Path | str, offset: int = 0) -> Iterator[tuple[int, str, dict]]:
    """Yield ``(index, tag, payload)`` for events with ``index >= offset``.

    A missing file yields nothing -- a live run may not have emitted its first
    event yet, which is not an error. A torn trailing line (the writer is
    mid-append) is skipped rather than raising; the next poll picks it up whole.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        index = row.get("i")
        if not isinstance(index, int) or index < offset:
            continue
        yield index, str(row.get("t", "")), dict(row.get("v") or {})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sessions_stream.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/sessions/stream.py tests/test_sessions_stream.py
git add src/resume_tailor_harness/sessions/stream.py tests/test_sessions_stream.py
git commit -m "feat(sessions): add stream events, ndjson codec, and sinks"
```

---

## Task 2: `AgentRunner.stream()`

**Files:**

- Modify: `src/resume_tailor_harness/llm_runner.py` (add to `AgentRunner`, after `arun`)
- Test: `tests/test_llm_runner_stream.py`

**Interfaces:**

- Consumes: Task 1's event types.
- Produces: `AgentRunner.stream(prompt) -> Iterator[StreamEvent]`, whose final yielded item is always `Completed()` or `Failed(...)`; and `AgentRunner.last_output` holding the terminal agno `RunOutput` after a successful stream (so callers can reach `.content` for the formatter).

**Context the implementer needs:** `AgentRunner.run` wraps every call in `refresh_agent_api_key` → `enforce_agent_budget` → call → `record_call`, retrying transient errors up to `Settings.llm_retries`. `stream` keeps that envelope but **retries only before the first token** — once bytes have been yielded, a silent retry would duplicate visible text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_runner_stream.py
import pytest

from resume_tailor_harness.llm_runner import AgentRunner
from resume_tailor_harness.sessions.stream import (
    Completed,
    Failed,
    ReasoningDelta,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)


class _Event:
    def __init__(self, event, **fields):
        self.event = event
        self.content = fields.pop("content", None)
        self.reasoning_content = fields.pop("reasoning_content", None)
        for key, value in fields.items():
            setattr(self, key, value)


class _Tool:
    def __init__(self, name, args=None, result=None, error=None):
        self.tool_name = name
        self.tool_args = args or {}
        self.result = result
        self.tool_call_error = error


class _Output:
    def __init__(self, content=""):
        self.content = content
        self.status = "COMPLETED"


class _FakeAgent:
    """Minimal agno-shaped agent: run(..., stream=True) yields events then output."""

    def __init__(self, script, *, fail_with=None, fail_after=0):
        self.script = script
        self.fail_with = fail_with
        self.fail_after = fail_after
        self.calls = 0
        self.model = None

    def run(self, prompt, **kwargs):
        self.calls += 1
        assert kwargs.get("stream") is True
        assert kwargs.get("stream_events") is True

        def gen():
            for index, event in enumerate(self.script):
                if self.fail_with is not None and index == self.fail_after:
                    raise self.fail_with
                yield event
            yield _Output("final")

        return gen()


class _Transient(Exception):
    status_code = 503


@pytest.fixture(autouse=True)
def _no_budget(monkeypatch):
    monkeypatch.setattr(
        "resume_tailor_harness.tenancy.limits.enforce_agent_budget", lambda agent: None
    )
    monkeypatch.setattr("resume_tailor_harness.tenancy.usage.record_call", lambda a, r: None)
    monkeypatch.setattr("resume_tailor_harness.llm_runner.refresh_agent_api_key", lambda a: None)


def test_stream_maps_content_events_to_text_deltas():
    agent = _FakeAgent([_Event("RunContent", content="Hel"), _Event("RunContent", content="lo")])
    events = list(AgentRunner(agent).stream("p"))
    assert events[:2] == [TextDelta("Hel"), TextDelta("lo")]
    assert events[-1] == Completed()


def test_stream_maps_reasoning_content_to_reasoning_deltas():
    agent = _FakeAgent([_Event("RunContent", reasoning_content="because")])
    events = list(AgentRunner(agent).stream("p"))
    assert ReasoningDelta("because") in events


def test_stream_maps_tool_events():
    agent = _FakeAgent(
        [
            _Event("ToolCallStarted", tool=_Tool("search_corpus", {"q": "Kafka"})),
            _Event("ToolCallCompleted", tool=_Tool("search_corpus", result="3 hits")),
        ]
    )
    events = list(AgentRunner(agent).stream("p"))
    assert any(isinstance(e, ToolStarted) and e.name == "search_corpus" for e in events)
    assert any(isinstance(e, ToolCompleted) and e.ok for e in events)


def test_tool_error_marks_the_completion_not_ok():
    agent = _FakeAgent(
        [_Event("ToolCallCompleted", tool=_Tool("probe", error="boom"))]
    )
    events = list(AgentRunner(agent).stream("p"))
    completed = [e for e in events if isinstance(e, ToolCompleted)]
    assert completed and completed[0].ok is False


def test_run_error_event_becomes_failed():
    agent = _FakeAgent([_Event("RunError", content="provider said no", error_type="Bad")])
    events = list(AgentRunner(agent).stream("p"))
    assert isinstance(events[-1], Failed)
    assert "provider said no" in events[-1].message


def test_transient_failure_before_first_token_retries(monkeypatch):
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.get_settings",
        lambda: _settings(retries=1),
    )
    agent = _FakeAgent([_Event("RunContent", content="hi")], fail_with=_Transient(), fail_after=0)

    def stop_failing():
        agent.fail_with = None

    events = []
    runner = AgentRunner(agent)
    # first attempt raises before yielding; second attempt succeeds
    original = agent.run

    def run(prompt, **kwargs):
        if agent.calls >= 1:
            stop_failing()
        return original(prompt, **kwargs)

    agent.run = run
    events = list(runner.stream("p"))
    assert agent.calls == 2
    assert TextDelta("hi") in events


def test_transient_failure_after_first_token_does_not_retry(monkeypatch):
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.get_settings", lambda: _settings(retries=3)
    )
    agent = _FakeAgent(
        [_Event("RunContent", content="hi"), _Event("RunContent", content="there")],
        fail_with=_Transient(),
        fail_after=1,
    )
    events = list(AgentRunner(agent).stream("p"))
    assert agent.calls == 1
    assert TextDelta("hi") in events
    assert isinstance(events[-1], Failed)


def test_last_output_is_available_after_a_successful_stream():
    agent = _FakeAgent([_Event("RunContent", content="hi")])
    runner = AgentRunner(agent)
    list(runner.stream("p"))
    assert runner.last_output.content == "final"


def _settings(retries: int):
    from resume_tailor_harness.config import Settings

    return Settings.model_construct(llm_retries=retries, llm_retry_delay=0.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_stream.py -v`
Expected: FAIL — `AttributeError: 'AgentRunner' object has no attribute 'stream'`

- [ ] **Step 3: Write the implementation**

Add this import near the other `resume_tailor_harness` imports in `llm_runner.py`:

```python
from resume_tailor_harness.sessions.stream import (
    Completed,
    Failed,
    ReasoningDelta,
    StreamEvent,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)
```

Add to `AgentRunner`, directly after `arun`:

```python
    def stream(self, prompt: str) -> Iterator[StreamEvent]:
        """Yield normalized events as the agent produces them.

        The same envelope as ``run`` -- key refresh, budget enforcement, usage
        recording -- but the retry rule differs: a transient failure is retried
        only **before the first event has been yielded**. Once bytes have reached
        the user a silent retry would duplicate visible text, so a later failure
        surfaces as ``Failed`` and the caller's retry affordance takes over.
        """
        settings = get_settings()
        for attempt in range(settings.llm_retries + 1):
            emitted = False
            try:
                refresh_agent_api_key(self._agent)
                from resume_tailor_harness.tenancy.limits import enforce_agent_budget

                enforce_agent_budget(self._agent)
                stream = self._agent.run(
                    prompt, stream=True, stream_events=True, yield_run_output=True
                )
                for raw in stream:
                    tag = str(getattr(raw, "event", "") or "")
                    if not tag:
                        # The terminal RunOutput, yielded because of
                        # yield_run_output=True. Record usage against it exactly
                        # as the blocking path does.
                        self.last_output = raw
                        from resume_tailor_harness.tenancy.usage import record_call

                        record_call(self._agent, raw)
                        continue
                    for event in _map_stream_event(tag, raw):
                        emitted = True
                        yield event
                        if isinstance(event, Failed):
                            return
                yield Completed()
                return
            except Exception as exc:
                retryable = (
                    not emitted
                    and attempt < settings.llm_retries
                    and is_transient(exc)
                )
                if not retryable:
                    yield Failed(str(exc), code=type(exc).__name__)
                    return
                time.sleep(settings.llm_retry_delay * (2**attempt))
```

Add `self.last_output: Any | None = None` to `AgentRunner.__init__`, and add this module-level helper below `AgentRunner`:

```python
def _preview(value: object, limit: int = 160) -> str:
    """Render a tool argument or result compactly for a UI chip."""
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _map_stream_event(tag: str, raw: Any) -> list[StreamEvent]:
    """Map one agno event onto zero or more of our own.

    Verified against agno 2.8.2: RunContentEvent carries both ``content`` and
    ``reasoning_content``, so one agno event can produce two of ours.
    """
    if tag in ("RunContent", "RunIntermediateContent"):
        events: list[StreamEvent] = []
        reasoning = getattr(raw, "reasoning_content", None)
        if isinstance(reasoning, str) and reasoning:
            events.append(ReasoningDelta(reasoning))
        content = getattr(raw, "content", None)
        if isinstance(content, str) and content:
            events.append(TextDelta(content))
        return events
    if tag == "ReasoningContentDelta":
        content = getattr(raw, "reasoning_content", None) or getattr(raw, "content", "")
        return [ReasoningDelta(content)] if isinstance(content, str) and content else []
    if tag == "ToolCallStarted":
        tool = getattr(raw, "tool", None)
        name = getattr(tool, "tool_name", "") or "tool"
        return [ToolStarted(name, _preview(getattr(tool, "tool_args", "")))]
    if tag in ("ToolCallCompleted", "ToolCallError"):
        tool = getattr(raw, "tool", None)
        name = getattr(tool, "tool_name", "") or "tool"
        error = getattr(tool, "tool_call_error", None)
        ok = tag == "ToolCallCompleted" and not error
        payload = error if error else getattr(tool, "result", "")
        return [ToolCompleted(name, _preview(payload), ok)]
    if tag == "RunError":
        message = getattr(raw, "content", "") or "The model reported an error."
        return [Failed(str(message), code=str(getattr(raw, "error_type", "") or "RunError"))]
    if tag == "RunCancelled":
        return [Failed(str(getattr(raw, "reason", "") or "cancelled"), code="CANCELLED")]
    return []
```

Also add `Iterator` to the `collections.abc` import line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_stream.py -v`
Expected: all PASS

- [ ] **Step 5: Verify nothing else broke, lint, and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/test_llm_runner.py tests/test_agent_json_mode.py -q
ruff check src/resume_tailor_harness/llm_runner.py tests/test_llm_runner_stream.py
git add src/resume_tailor_harness/llm_runner.py tests/test_llm_runner_stream.py
git commit -m "feat(llm): stream agent events with retry only before first token"
```

---

## Task 3: `ProseEmitter` — delimiter splitting with holdback

**Files:**

- Modify: `src/resume_tailor_harness/sessions/turns.py`
- Test: `tests/test_turn_prose.py`

**Interfaces:**

- Consumes: Task 1's `StreamSink`, `TextDelta`.
- Produces: `DELIMITER = "---METADATA---"`; `ProseEmitter(sink, holdback=32)` with `feed(text)`, `finish() -> tuple[str, str]` returning `(prose, full_output)`.

**Why the holdback exists:** deltas arrive at arbitrary boundaries. Without it, a chunk ending in `---METADAT` would be emitted to the user before the next chunk revealed it was the delimiter.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_turn_prose.py
from resume_tailor_harness.sessions.stream import TextDelta
from resume_tailor_harness.sessions.turns import DELIMITER, ProseEmitter


class _Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        return None

    @property
    def text(self):
        return "".join(e.text for e in self.events if isinstance(e, TextDelta))


def test_prose_before_the_delimiter_is_emitted():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("Hello there.\n" + DELIMITER + "\naction: ask")
    prose, full = emitter.finish()
    assert prose == "Hello there."
    assert sink.text == "Hello there."
    assert "action: ask" in full


def test_metadata_is_never_emitted_to_the_sink():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("Hi.\n" + DELIMITER + "\ntopic: t3")
    emitter.finish()
    assert "topic: t3" not in sink.text
    assert "METADATA" not in sink.text


def test_delimiter_split_across_chunks_never_leaks_a_partial():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    for chunk in ["Good answer.\n", "---METAD", "ATA---\n", "action: draft"]:
        emitter.feed(chunk)
    prose, _ = emitter.finish()
    assert prose == "Good answer."
    assert "---METAD" not in sink.text
    assert "METADATA" not in sink.text


def test_missing_delimiter_treats_everything_as_prose():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("Just a message with no metadata block at all.")
    prose, full = emitter.finish()
    assert prose == "Just a message with no metadata block at all."
    assert full == prose
    assert sink.text == prose


def test_holdback_is_flushed_on_finish():
    sink = _Recorder()
    emitter = ProseEmitter(sink, holdback=32)
    emitter.feed("short")
    assert sink.text == ""  # still inside the holdback window
    prose, _ = emitter.finish()
    assert prose == "short"
    assert sink.text == "short"


def test_long_prose_streams_before_finish():
    sink = _Recorder()
    emitter = ProseEmitter(sink, holdback=8)
    emitter.feed("abcdefghijklmnop")
    assert sink.text == "abcdefgh"
    emitter.finish()
    assert sink.text == "abcdefghijklmnop"


def test_full_output_preserves_everything_for_the_formatter():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("Prose.\n" + DELIMITER + "\naction: draft\nquote: \"we cut p99\"")
    _, full = emitter.finish()
    assert DELIMITER in full
    assert "we cut p99" in full
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_turn_prose.py -v`
Expected: FAIL — `ImportError: cannot import name 'DELIMITER'`

- [ ] **Step 3: Write the implementation**

Append to `src/resume_tailor_harness/sessions/turns.py`:

```python
from resume_tailor_harness.sessions.stream import StreamSink, TextDelta

#: Separates the persona agent's user-facing prose from its structured metadata.
#: Everything before it streams; everything after is buffered for the formatter.
DELIMITER = "---METADATA---"


class ProseEmitter:
    """Split a streamed persona response into visible prose and buffered metadata.

    Deltas arrive at arbitrary boundaries, so a naive implementation emits
    ``---METADAT`` to the user and only discovers on the next chunk that it was
    the delimiter. ``holdback`` withholds a trailing window (the delimiter length
    plus margin) until either more text arrives or the stream finishes.

    A response with no delimiter is entirely prose -- the model failing to follow
    the metadata contract degrades to today's behavior rather than failing.
    """

    def __init__(self, sink: StreamSink, holdback: int = 32) -> None:
        self._sink = sink
        self._holdback = max(holdback, len(DELIMITER))
        self._raw: list[str] = []
        self._prose: list[str] = []
        self._pending = ""
        self._done = False

    def feed(self, text: str) -> None:
        self._raw.append(text)
        if self._done:
            return
        self._pending += text
        cut = self._pending.find(DELIMITER)
        if cut != -1:
            self._flush(self._pending[:cut])
            self._pending = ""
            self._done = True
            return
        safe = len(self._pending) - self._holdback
        if safe > 0:
            self._flush(self._pending[:safe])
            self._pending = self._pending[safe:]

    def _flush(self, text: str) -> None:
        if not text:
            return
        self._prose.append(text)
        self._sink.emit(TextDelta(text))

    def finish(self) -> tuple[str, str]:
        """Return ``(prose, full_output)``; flushes any held-back tail."""
        if not self._done:
            self._flush(self._pending)
            self._pending = ""
            self._done = True
        return "".join(self._prose).strip(), "".join(self._raw)
```

Note: `finish()` strips the prose, so the trailing newline before the delimiter never reaches storage. The already-emitted deltas may include it; the UI renders markdown, where a trailing newline is invisible.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_turn_prose.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/sessions/turns.py tests/test_turn_prose.py
git add src/resume_tailor_harness/sessions/turns.py tests/test_turn_prose.py
git commit -m "feat(sessions): split streamed prose from buffered turn metadata"
```

---

## Task 4: Validation split — `DraftRejected`, strict/lenient, durable notices

**Files:**

- Modify: `src/resume_tailor_harness/sessions/turns.py`, `src/resume_tailor_harness/profile/coach.py`, `src/resume_tailor_harness/profile/coach_store.py`, `src/resume_tailor_harness/interview/agent.py`, `src/resume_tailor_harness/interview/store.py`, `src/resume_tailor_harness/api/schemas/coach.py`, `src/resume_tailor_harness/api/schemas/interview.py`, `src/resume_tailor_harness/services/profile_coach.py` (view projection only)
- Test: `tests/test_profile_coach.py` (extend), `tests/test_interview_agent.py` (extend)

**Interfaces:**

- Consumes: `TurnRejected` (existing).
- Produces: `DraftRejected(TurnRejected)`; `format_with_retry(formatter, notes, schema, validate, *, label)` where `validate` now takes `(formatted, strict: bool)`; `ValidatedTurn.notice: str`; `CoachTurnRecord.notice: str`; `InterviewTurnRecord.notice: str`; `CoachTurnOut.notice`, `InterviewTurnOut.notice`.

**The rule:** attempt 1 validates `strict=True` (a bad draft raises). The single retry validates `strict=False` (a bad draft is dropped and becomes a notice; structural failures still raise). A structural failure that survives the retry propagates to the caller, which degrades in Task 5/6.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_profile_coach.py
from resume_tailor_harness.profile.coach import CoachTurn, DraftNote, normalize_turn
from resume_tailor_harness.sessions.turns import DraftRejected, TurnRejected


def _session_with_answer(answer: str) -> dict:
    return {
        "status": "active",
        "topics": [
            {"id": "t1", "gap": "scope", "why_it_matters": "", "related_ref": "", "status": "open", "note_doc_id": ""}
        ],
        "draft_notes": [],
        "turns": [{"role": "user", "kind": "", "text": answer, "topic_id": "t1", "at": "", "research_actions": []}],
    }


def test_fabricated_quote_raises_draft_rejected_when_strict():
    session = _session_with_answer("I led the migration.")
    turn = CoachTurn(
        message="Nice.",
        action="draft",
        topic_id="t1",
        draft_note=DraftNote(title="T", summary="S", quotes=["I invented this"]),
    )
    with pytest.raises(DraftRejected):
        normalize_turn(turn, session, strict=True)


def test_fabricated_quote_degrades_to_a_notice_when_lenient():
    session = _session_with_answer("I led the migration.")
    turn = CoachTurn(
        message="Nice.",
        action="draft",
        topic_id="t1",
        draft_note=DraftNote(title="T", summary="S", quotes=["I invented this"]),
    )
    validated = normalize_turn(turn, session, strict=False)
    assert validated.draft is None
    assert "quote check" in validated.notice.lower()
    assert validated.coach_turn.text == "Nice."
    assert validated.coach_turn.notice == validated.notice


def test_unknown_topic_still_raises_even_when_lenient():
    session = _session_with_answer("I led the migration.")
    turn = CoachTurn(message="Nice.", action="ask", topic_id="tZZ")
    with pytest.raises(TurnRejected):
        normalize_turn(turn, session, strict=False)


def test_draft_rejected_is_a_turn_rejected_so_callers_still_catch_it():
    assert issubclass(DraftRejected, TurnRejected)


def test_valid_draft_is_unaffected_by_lenient_mode():
    session = _session_with_answer("We cut p99 latency from 800ms to 120ms.")
    turn = CoachTurn(
        message="Good.",
        action="draft",
        topic_id="t1",
        draft_note=DraftNote(title="T", summary="S", quotes=["We cut p99 latency from 800ms to 120ms."]),
    )
    validated = normalize_turn(turn, session, strict=False)
    assert validated.draft is not None
    assert validated.notice == ""
```

```python
# append to tests/test_sessions_turns.py (create if absent)
from resume_tailor_harness.sessions.turns import format_with_retry


class _Formatter:
    def __init__(self, results):
        self.results = list(results)
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.results.pop(0))


def test_format_with_retry_calls_validate_strict_then_lenient():
    seen = []

    def validate(formatted, strict):
        seen.append(strict)
        if strict:
            raise DraftRejected("bad quote")
        return "degraded"

    formatter = _Formatter([_Schema(), _Schema()])
    result = format_with_retry(formatter, "notes", _Schema, validate, label="NOTES")
    assert seen == [True, False]
    assert result == "degraded"


def test_format_with_retry_returns_first_attempt_when_it_validates():
    def validate(formatted, strict):
        assert strict is True
        return "ok"

    formatter = _Formatter([_Schema()])
    assert format_with_retry(formatter, "notes", _Schema, validate, label="NOTES") == "ok"
```

(`_Schema` is a trivial `ExtensibleModel` subclass defined at the top of the test file; `SimpleNamespace` from `types`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach.py tests/test_sessions_turns.py -v`
Expected: FAIL — `ImportError: cannot import name 'DraftRejected'`

- [ ] **Step 3: Write the implementation**

In `sessions/turns.py`:

```python
class DraftRejected(TurnRejected):
    """A draft note failed its integrity gate.

    Distinct from a structural rejection because the two degrade differently: a
    bad draft is dropped and the turn survives, while an unrecoverable structural
    problem forces the caller to degrade the whole turn. It subclasses
    ``TurnRejected`` so every existing ``except TurnRejected`` still catches it.
    """
```

Replace `format_with_retry`'s body so `validate` takes `(formatted, strict)`:

```python
def format_with_retry(formatter, notes: object, schema, validate, *, label: str):
    """Format untrusted notes into ``schema`` and validate, retrying once.

    ``validate(formatted, strict)`` is called with ``strict=True`` first. The
    retry feeds the rejection reason back to the formatter and validates with
    ``strict=False``, which lets a draft-level failure degrade to a notice rather
    than destroying a turn whose prose the user has already read. A structural
    rejection still propagates. Non-``schema`` output raises
    ``UnparsedAgentOutput`` (a TypeError) immediately.
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
        return validate(retry, False)
```

In `profile/coach.py`:

- Add `notice: str = ""` to `ValidatedTurn`.
- Change `normalize_turn(turn, session)` to `normalize_turn(turn, session, *, strict: bool = True)`.
- Wrap the draft block so its failures raise `DraftRejected` when `strict`, and set `notice` + `draft = None` otherwise:

```python
    draft: CoachDraftNote | None = None
    notice = ""
    if turn.action == "draft":
        try:
            draft = _build_draft(turn, topic, session, skipped)
        except DraftRejected:
            if strict:
                raise
            draft = None
            notice = "Note not attached — quote check failed."
    elif turn.draft_note is not None:
        raise TurnRejected("draft note on a non-draft turn")
```

Move the existing draft-building block verbatim into `_build_draft(turn, topic, session, skipped) -> CoachDraftNote`, changing each of its `raise TurnRejected(...)` calls to `raise DraftRejected(...)`. Then thread `notice` into the returned record:

```python
    return ValidatedTurn(
        coach_turn=CoachTurnRecord(
            role="coach",
            kind="draft_note" if draft is not None else "question",
            text=message,
            topic_id=turn.topic_id,
            notice=notice,
            research_actions=_actions(turn),
        ),
        new_topics=new_topics,
        skipped_topic_ids=skipped,
        draft=draft,
        notice=notice,
    )
```

Give `normalize_opening` and `normalize_recap` the same `*, strict: bool = True` keyword (they have no draft path, so they ignore it) — every `validate` callable now receives two arguments.

Add `notice: str = ""` to `CoachTurnRecord` (`profile/coach_store.py`) and to `InterviewTurnRecord` (`interview/store.py`).

Apply the identical treatment to `interview/agent.py::normalize_turn`.

In `services/profile_coach.py`, add `"notice": turn["notice"]` to `_camel_turn`; do the same in `services/mock_interview.py::_turn_view`. Add `notice: str = ""` to `CoachTurnOut` and `InterviewTurnOut`.

Update the two existing `format_with_retry` call sites (`services/profile_coach.py`, `services/mock_interview.py`) to two-argument lambdas, e.g.:

```python
        lambda turn, strict: normalize_turn(turn, preview, strict=strict),
```

- [ ] **Step 4: Run the full backend suite to verify nothing regressed**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach.py tests/test_sessions_turns.py tests/test_interview_agent.py tests/test_profile_coach_service.py tests/test_mock_interview_service.py -v`
Expected: all PASS

- [ ] **Step 5: Regenerate contracts, lint, commit**

```bash
bash scripts/gen_ts_client.sh
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q
ruff check src tests
git add -A
git commit -m "feat(sessions): scope the draft integrity gate so a bad quote spares the turn"
```

---

## Task 5: Stream the coach turn

**Files:**

- Modify: `src/resume_tailor_harness/services/profile_coach.py`, `src/resume_tailor_harness/profile/coach.py` (instructions), `src/resume_tailor_harness/config.py`
- Test: `tests/test_profile_coach_service.py` (extend)

**Interfaces:**

- Consumes: `AgentRunner.stream`, `ProseEmitter`, `StreamSink`, `NullSink`, `Settings.stream_enabled`.
- Produces: `run_opening_turn(..., sink: StreamSink | None = None)`, `run_message_turn(..., sink: StreamSink | None = None)`, `run_recap_turn(..., sink: StreamSink | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_profile_coach_service.py
from resume_tailor_harness.sessions.stream import Completed, TextDelta, ToolStarted
from resume_tailor_harness.services.profile_coach import run_message_turn


class _StreamingCoach:
    """Fake persona agent that streams prose then a metadata block."""

    def __init__(self, prose, metadata="action: ask\ntopic: t1"):
        self.prose = prose
        self.metadata = metadata

    def stream(self, prompt):
        for word in self.prose.split(" "):
            yield TextDelta(word + " ")
        yield ToolStarted("search_corpus", "Kafka")
        yield TextDelta("\n---METADATA---\n" + self.metadata)
        yield Completed()

    def run(self, prompt):
        return SimpleNamespace(content=self.prose + "\n---METADATA---\n" + self.metadata)


def test_streamed_prose_reaches_the_sink_and_becomes_the_stored_turn(tmp_path, coach_session):
    sink = _Recorder()
    run_message_turn(
        _reporter(),
        profile_dir=tmp_path,
        session_id=coach_session,
        message="We cut p99 from 800ms to 120ms.",
        coach_agent=_StreamingCoach("Strong answer."),
        formatter_agent=_formatter_returning(CoachTurn(message="IGNORED", action="ask", topic_id="t1")),
        sink=sink,
    )
    assert "Strong answer." in sink.text
    view = session_view(tmp_path, coach_session)
    assert view["turns"][-1]["text"] == "Strong answer."


def test_formatter_message_is_ignored_when_a_stream_produced_prose(tmp_path, coach_session):
    run_message_turn(
        _reporter(),
        profile_dir=tmp_path,
        session_id=coach_session,
        message="answer",
        coach_agent=_StreamingCoach("Streamed text."),
        formatter_agent=_formatter_returning(CoachTurn(message="Formatter text.", action="ask", topic_id="t1")),
        sink=_Recorder(),
    )
    assert session_view(tmp_path, coach_session)["turns"][-1]["text"] == "Streamed text."


def test_tool_events_reach_the_sink(tmp_path, coach_session):
    sink = _Recorder()
    run_message_turn(
        _reporter(), profile_dir=tmp_path, session_id=coach_session, message="answer",
        coach_agent=_StreamingCoach("Text."),
        formatter_agent=_formatter_returning(CoachTurn(message="", action="ask", topic_id="t1")),
        sink=sink,
    )
    assert any(isinstance(event, ToolStarted) for event in sink.events)


def test_stream_disabled_uses_the_blocking_path_and_the_formatter_message(tmp_path, coach_session, monkeypatch):
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_coach.get_settings",
        lambda: Settings.model_construct(stream_enabled=False),
    )
    sink = _Recorder()
    run_message_turn(
        _reporter(), profile_dir=tmp_path, session_id=coach_session, message="answer",
        coach_agent=_StreamingCoach("Streamed text."),
        formatter_agent=_formatter_returning(CoachTurn(message="Formatter text.", action="ask", topic_id="t1")),
        sink=sink,
    )
    assert sink.events == []
    assert session_view(tmp_path, coach_session)["turns"][-1]["text"] == "Formatter text."


def test_empty_streamed_prose_falls_back_to_the_formatter_message(tmp_path, coach_session):
    run_message_turn(
        _reporter(), profile_dir=tmp_path, session_id=coach_session, message="answer",
        coach_agent=_StreamingCoach(""),
        formatter_agent=_formatter_returning(CoachTurn(message="Fallback.", action="ask", topic_id="t1")),
        sink=_Recorder(),
    )
    assert session_view(tmp_path, coach_session)["turns"][-1]["text"] == "Fallback."


def test_a_dropped_draft_notice_survives_a_session_reload(tmp_path, coach_session):
    run_message_turn(
        _reporter(), profile_dir=tmp_path, session_id=coach_session, message="I led it.",
        coach_agent=_StreamingCoach("Drafted."),
        formatter_agent=_formatter_returning(
            CoachTurn(message="", action="draft", topic_id="t1",
                      draft_note=DraftNote(title="T", summary="S", quotes=["never said this"]))
        ),
        sink=_Recorder(),
    )
    turn = session_view(tmp_path, coach_session)["turns"][-1]
    assert "quote check" in turn["notice"].lower()
    assert session_view(tmp_path, coach_session)["draftNotes"] == []
```

`_Recorder` is the sink double from Task 3's tests — lift it into `tests/conftest.py` as a shared fixture rather than duplicating it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach_service.py -v -k stream`
Expected: FAIL — `TypeError: run_message_turn() got an unexpected keyword argument 'sink'`

- [ ] **Step 3: Write the implementation**

Add to `config.py`, beside `browser_enabled`:

```python
    #: Stream conversational turns token-by-token. Setting this false restores
    #: the blocking path: the persona agent is called with `run`, the sink is
    #: discarded, and the formatter's `message` is authoritative again. It exists
    #: because streaming changes which agent authors the visible message, and
    #: that is worth being able to revert without a redeploy.
    stream_enabled: bool = True
```

Add to `services/profile_coach.py`:

```python
def _persona_output(agent, prompt: str, sink: StreamSink, *, source: str) -> tuple[str, str]:
    """Run the persona agent and return ``(prose, full_notes)``.

    When streaming is on, the prose is what the user actually saw and becomes the
    stored turn text -- the formatter's ``message`` is then redundant. When it is
    off, the prose is empty and the caller falls back to the formatter.
    """
    if not get_settings().stream_enabled:
        return "", expect_text(agent.run(prompt), source=source)
    emitter = ProseEmitter(sink)
    failure: Failed | None = None
    for event in agent.stream(prompt):
        if isinstance(event, TextDelta):
            emitter.feed(event.text)
        elif isinstance(event, Failed):
            failure = event
        else:
            sink.emit(event)
    prose, full = emitter.finish()
    if failure is not None and not prose:
        raise RuntimeError(failure.message)
    return prose, full
```

In `run_message_turn`, replace the `notes = expect_text(coach.run(prompt), ...)` line with:

```python
    prose, notes = _persona_output(coach, prompt, sink or NullSink(), source="coach notes")
```

and after `format_with_retry` returns, override the stored text when a stream produced prose:

```python
    if prose:
        validated.coach_turn = validated.coach_turn.model_copy(update={"text": prose})
    if validated.notice:
        (sink or NullSink()).emit(Notice(validated.notice))
```

Wrap the `format_with_retry` call so an unrecoverable structural rejection degrades instead of failing the turn:

```python
    try:
        validated = format_with_retry(
            formatter, notes, CoachTurn,
            lambda turn, strict: normalize_turn(turn, preview, strict=strict),
            label="COACH NOTES",
        )
    except TurnRejected as exc:
        if not prose:
            raise
        validated = _degraded_turn(session, prose, reason=str(exc))
```

with:

```python
def _degraded_turn(session: dict, prose: str, *, reason: str) -> ValidatedTurn:
    """Keep a turn whose prose the user already read when structure is unusable.

    Falls back to the session's first open topic so the agenda stays coherent.
    """
    open_topics = [t["id"] for t in session["topics"] if t["status"] == "open"]
    topic_id = open_topics[0] if open_topics else (session["topics"][0]["id"] if session["topics"] else "")
    notice = "Some of this turn's structure could not be read, so no note was attached."
    return ValidatedTurn(
        coach_turn=CoachTurnRecord(role="coach", kind="question", text=prose, topic_id=topic_id, notice=notice),
        notice=notice,
    )
```

Add `sink: StreamSink | None = None` to `run_opening_turn`, `run_message_turn`, and `run_recap_turn`, applying the same `_persona_output` swap in each.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach_service.py -v`
Expected: all PASS

- [ ] **Step 5: Add the metadata contract to the coach instructions**

Append to `_COACH_INSTRUCTIONS` in `profile/coach.py`:

```python
    "Write your reply to the user first, as plain prose with no preamble and no "
    "headings. Then, on its own line, emit exactly `---METADATA---` followed by "
    "your structured decisions: the action (ask/draft), the topic id, any topic "
    "updates, the draft note with its exact user quotes, and any research "
    "actions. Everything above the marker is shown to the user verbatim; "
    "everything below it never is.",
```

Add the mirrored line to `interview/agent.py::persona_instructions` in Task 6.

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_prompt_contracts.py -v`
Expected: PASS (update the registry snapshot if that test pins instruction text)

- [ ] **Step 6: Lint and commit**

```bash
ruff check src tests
git add -A
git commit -m "feat(coach): stream persona prose and store it as the turn text"
```

---

## Task 6: Stream the interview turn

**Files:**

- Modify: `src/resume_tailor_harness/services/mock_interview.py`, `src/resume_tailor_harness/interview/agent.py`
- Test: `tests/test_mock_interview_service.py` (extend)

**Interfaces:**

- Consumes: everything from Task 5.
- Produces: `run_opening_turn(..., sink=None)`, `run_answer_turn(..., sink=None)` in `services/mock_interview.py`. `run_debrief_turn` is **unchanged** — the debrief is a structured scorecard, not prose.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_mock_interview_service.py
def test_interview_answer_streams_prose_and_stores_it(tmp_path, interview_session):
    sink = _Recorder()
    run_answer_turn(
        _reporter(), interview_dir=tmp_path, session_id=interview_session,
        message="I owned the migration end to end.",
        interviewer_agent=_StreamingInterviewer("Walk me through the rollback plan."),
        formatter_agent=_formatter_returning(InterviewTurn(message="IGNORED", question_id="q1")),
        sink=sink,
    )
    assert "rollback plan" in sink.text
    assert session_view(tmp_path, interview_session)["turns"][-1]["text"].endswith("rollback plan.")


def test_debrief_does_not_stream(tmp_path, interview_session):
    sink = _Recorder()
    run_debrief_turn(_reporter(), interview_dir=tmp_path, session_id=interview_session,
                     debrief_agent=_debrief_agent(), formatter_agent=_debrief_formatter())
    assert sink.events == []


def test_interview_turn_carries_a_notice_field(tmp_path, interview_session):
    view = session_view(tmp_path, interview_session)
    assert "notice" in view["turns"][0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mock_interview_service.py -v -k "stream or notice"`
Expected: FAIL — `TypeError: run_answer_turn() got an unexpected keyword argument 'sink'`

- [ ] **Step 3: Write the implementation**

Move `_persona_output` and `_degraded_turn` from `services/profile_coach.py` into `sessions/turns.py` (they are stack-agnostic) and import them in both services. `_degraded_turn` becomes generic by taking the record constructor:

```python
def persona_output(agent, prompt: str, sink: StreamSink, *, source: str) -> tuple[str, str]:
    ...  # body from Task 5, unchanged
```

In `services/mock_interview.py`, add `sink: StreamSink | None = None` to `run_opening_turn` and `run_answer_turn`, replace each `expect_text(interviewer.run(prompt), ...)` with `persona_output(...)`, override the stored text with the prose when non-empty, and emit `Notice` when the validated turn carries one. Leave `run_debrief_turn` alone.

Append the metadata-contract instruction (same wording as Task 5, with "candidate" instead of "user") to `persona_instructions` in `interview/agent.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mock_interview_service.py tests/test_profile_coach_service.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src tests
git add -A
git commit -m "feat(interview): stream interviewer prose; leave the debrief structured"
```

---

## Task 7: Run stream path, SSE route, and router wiring

**Files:**

- Create: `src/resume_tailor_harness/api/runs/stream_sse.py`, `tests/api/test_run_stream_route.py`
- Modify: `src/resume_tailor_harness/api/runs/manager.py`, `src/resume_tailor_harness/api/routers/runs.py`, `src/resume_tailor_harness/api/routers/coach.py`, `src/resume_tailor_harness/api/routers/interview.py`

**Interfaces:**

- Consumes: `read_stream`, `TERMINAL_TAGS`, `RunStreamSink`.
- Produces: `RunManager.stream_path(run_id) -> Path`; `stream_events(mgr, run_id, offset, poll_interval=0.25) -> AsyncIterator[dict]`; route `GET /api/runs/{run_id}/stream?offset=N`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_run_stream_route.py
import json


def test_stream_route_replays_from_offset_zero(client, seeded_stream_run):
    run_id = seeded_stream_run
    with client.stream("GET", f"/api/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        rows = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert [row["i"] for row in rows] == [0, 1, 2]
    assert rows[-1]["t"] == "completed"


def test_stream_route_honours_offset(client, seeded_stream_run):
    with client.stream("GET", f"/api/runs/{seeded_stream_run}/stream?offset=2") as response:
        rows = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert [row["i"] for row in rows] == [2]


def test_stream_route_requires_auth(unauthed_client, seeded_stream_run):
    response = unauthed_client.get(f"/api/runs/{seeded_stream_run}/stream")
    assert response.status_code == 401


def test_stream_route_404s_for_a_run_the_caller_does_not_own(client):
    assert client.get("/api/runs/does-not-exist/stream").status_code == 404


def test_stream_route_returns_empty_for_a_live_run_with_no_events_yet(client, empty_stream_run):
    with client.stream("GET", f"/api/runs/{empty_stream_run}/stream") as response:
        assert response.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_stream_route.py -v`
Expected: FAIL — 404 on every case (route does not exist)

- [ ] **Step 3: Write the implementation**

Add to `RunManager`:

```python
    def stream_path(self, run_id: str) -> Path:
        """Where this run's ndjson event log lives.

        Resolved through the run's registered root so the file lands under the
        same tenant directory as its record. Never built from client input.
        """
        return self._root_for(run_id) / f"{run_id}.stream.ndjson"
```

Create `src/resume_tailor_harness/api/runs/stream_sse.py`:

```python
"""Tail a run's ndjson event log as SSE.

Separate from ``sse.run_events`` on purpose: that one projects a ``RunOut`` and
serves every run kind. This one carries conversational turn events and is polled
faster, because a user is watching text appear.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from resume_tailor_harness.sessions.stream import TERMINAL_TAGS, read_stream

#: Give up on a run whose record went terminal but whose log never closed, so a
#: crashed worker cannot hold a connection open forever.
_GRACE_POLLS = 4


async def stream_events(
    mgr, run_id: str, offset: int = 0, *, poll_interval: float = 0.25
) -> AsyncIterator[dict]:
    """Yield sse-starlette event dicts for events at ``index >= offset``."""
    path = mgr.stream_path(run_id)
    cursor = max(offset, 0)
    grace = 0
    while True:
        emitted_terminal = False
        for index, tag, payload in read_stream(path, cursor):
            cursor = index + 1
            yield {"data": json.dumps({"i": index, "t": tag, "v": payload})}
            if tag in TERMINAL_TAGS:
                emitted_terminal = True
        if emitted_terminal:
            return
        snapshot = mgr.get(run_id)
        if snapshot is None or snapshot.state in ("done", "error", "cancelled"):
            grace += 1
            if grace >= _GRACE_POLLS:
                yield {"data": json.dumps({"i": cursor, "t": "completed", "v": {}})}
                return
        await asyncio.sleep(poll_interval)
```

Add to `api/routers/runs.py`, beside `stream_run`:

```python
@link_router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    offset: int = 0,
    mgr: RunManager = Depends(get_run_manager),
    _context=Depends(get_sse_user_context),
):
    """Tail a conversational run's token stream from ``offset``.

    Distinct from ``/events``, which projects the RunOut for every run kind.
    """
    _owned_record(mgr, run_id)
    return EventSourceResponse(stream_events(mgr, run_id, offset))
```

In `api/routers/coach.py`, build the sink inside the worker so it uses the run's own id:

```python
def _submit(manager: RunManager, kind: str, work) -> RunOut:
    def with_sink(reporter):
        sink = RunStreamSink(manager.stream_path(reporter.run_id))
        try:
            return work(reporter, sink)
        finally:
            sink.close()

    return launch(
        manager, kind, with_sink,
        singleton_key=_SINGLETON, singleton_conflict="raise",
        busy_code="COACH_BUSY", busy_message="A coach turn is already running",
    )
```

and change each `work` closure to accept `(reporter, sink)` and forward `sink=sink`. Apply the same change in `api/routers/interview.py`.

If `RunProgressReporter` does not already expose `run_id`, add it as a read-only attribute set in `__init__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_stream_route.py tests/api/ -q`
Expected: all PASS

- [ ] **Step 5: Regenerate contracts, lint, commit**

```bash
bash scripts/gen_ts_client.sh
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q
ruff check src tests
git add -A
git commit -m "feat(api): tail conversational run events over SSE with offset resume"
```

---

## Task 8: CLI console streaming

**Files:**

- Modify: `src/resume_tailor_harness/cli.py` (`profile_coach_cmd`, around lines 317-460)
- Test: `tests/test_cli_profile_coach.py` (extend)

**Interfaces:**

- Consumes: `ConsoleStreamSink`.
- Produces: no new public API — the CLI passes `sink=ConsoleStreamSink(...)` into `run_opening_turn`, `run_message_turn`, and `run_recap_turn`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_cli_profile_coach.py
def test_cli_coach_prints_streamed_prose_incrementally(tmp_path, monkeypatch, capsys):
    captured: list[object] = []

    def fake_turn(reporter, *, sink=None, **kwargs):
        assert sink is not None, "the CLI must pass a console sink"
        sink.emit(TextDelta("Streamed "))
        sink.emit(TextDelta("reply."))
        sink.close()
        captured.append(sink)
        return _session_view_stub()

    monkeypatch.setattr("resume_tailor_harness.services.profile_coach.run_message_turn", fake_turn)
    result = runner.invoke(app, ["profile", "coach"], input="my answer\n/quit\n")
    assert "Streamed reply." in result.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_profile_coach.py -v -k streamed`
Expected: FAIL — `AssertionError: the CLI must pass a console sink`

- [ ] **Step 3: Write the implementation**

In `profile_coach_cmd`, build one sink and pass it to each turn call:

```python
    from resume_tailor_harness.sessions.stream import ConsoleStreamSink

    def _write(text: str) -> None:
        typer.echo(text, nl=False)

    sink = ConsoleStreamSink(_write)
```

Then add `sink=sink` to the `run_opening_turn`, `run_message_turn`, and `run_recap_turn` calls. Because the sink now prints the coach's reply as it arrives, remove the subsequent `typer.echo(view["turns"][-1]["text"])` that would otherwise print it a second time — but keep it behind `if not get_settings().stream_enabled:` so the kill switch still produces output.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_profile_coach.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/cli.py tests/test_cli_profile_coach.py
git add -A
git commit -m "feat(cli): stream coach replies to the terminal"
```

---

## Task 9: Web stream types and `useChatStream`

**Files:**

- Create: `web/src/lib/chat/events.ts`, `web/src/lib/chat/useChatStream.ts`, `web/src/lib/chat/events.test.ts`, `web/src/lib/chat/useChatStream.test.ts`
- Create: `tests/api/test_stream_event_parity.py`

**Interfaces:**

- Consumes: the SSE route from Task 7.
- Produces: TS types `StreamEventTag`, `ChatPart` (`{ kind: "text" | "reasoning" | "tool" | "notice"; ... }`), `reduceEvent(parts, event) -> ChatPart[]`, and `useChatStream(runId, options) -> { parts, status, error, stop, reset }`.

**Why a hand-written type:** OpenAPI cannot describe an SSE body, so `contracts/ts/api.ts` will never contain these. The parity test is what stops the two definitions drifting.

- [ ] **Step 1: Write the failing tests**

```typescript
// web/src/lib/chat/events.test.ts
import { describe, expect, it } from "vitest";
import { STREAM_EVENT_TAGS, reduceEvent, type ChatPart } from "./events";

describe("reduceEvent", () => {
  it("appends the first text delta as a text part", () => {
    expect(reduceEvent([], { i: 0, t: "text", v: { text: "Hel" } })).toEqual([
      { kind: "text", text: "Hel" },
    ]);
  });

  it("coalesces consecutive text deltas into one part", () => {
    let parts: ChatPart[] = [];
    parts = reduceEvent(parts, { i: 0, t: "text", v: { text: "Hel" } });
    parts = reduceEvent(parts, { i: 1, t: "text", v: { text: "lo" } });
    expect(parts).toEqual([{ kind: "text", text: "Hello" }]);
  });

  it("starts a new text part after a tool part so order is preserved", () => {
    let parts: ChatPart[] = [];
    parts = reduceEvent(parts, { i: 0, t: "text", v: { text: "a" } });
    parts = reduceEvent(parts, {
      i: 1,
      t: "tool_started",
      v: { name: "search", argsPreview: "x" },
    });
    parts = reduceEvent(parts, { i: 2, t: "text", v: { text: "b" } });
    expect(parts.map((p) => p.kind)).toEqual(["text", "tool", "text"]);
  });

  it("resolves a tool part in place when it completes", () => {
    let parts: ChatPart[] = [];
    parts = reduceEvent(parts, {
      i: 0,
      t: "tool_started",
      v: { name: "search", argsPreview: "x" },
    });
    parts = reduceEvent(parts, {
      i: 1,
      t: "tool_completed",
      v: { name: "search", resultPreview: "3 hits", ok: true },
    });
    expect(parts).toEqual([
      {
        kind: "tool",
        name: "search",
        argsPreview: "x",
        resultPreview: "3 hits",
        ok: true,
        done: true,
      },
    ]);
  });

  it("keeps reasoning in its own part", () => {
    const parts = reduceEvent([], { i: 0, t: "reasoning", v: { text: "why" } });
    expect(parts).toEqual([{ kind: "reasoning", text: "why" }]);
  });

  it("appends a notice part", () => {
    const parts = reduceEvent([], {
      i: 0,
      t: "notice",
      v: { message: "not attached" },
    });
    expect(parts).toEqual([{ kind: "notice", message: "not attached" }]);
  });

  it("ignores an unknown tag rather than throwing", () => {
    expect(reduceEvent([], { i: 0, t: "future_tag", v: {} } as never)).toEqual(
      [],
    );
  });

  it("exports every tag the backend can emit", () => {
    expect([...STREAM_EVENT_TAGS].sort()).toEqual([
      "completed",
      "failed",
      "notice",
      "reasoning",
      "text",
      "tool_completed",
      "tool_started",
    ]);
  });
});
```

```typescript
// web/src/lib/chat/useChatStream.test.ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useChatStream } from "./useChatStream";

class FakeEventSource {
  static last: FakeEventSource | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.last = this;
  }
  close() {
    this.closed = true;
  }
  send(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

vi.stubGlobal("EventSource", FakeEventSource);

describe("useChatStream", () => {
  it("accumulates parts from events", async () => {
    const { result } = renderHook(() => useChatStream("run-1"));
    act(() =>
      FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "hi" } }),
    );
    await waitFor(() => expect(result.current.parts).toHaveLength(1));
  });

  it("closes and reports done on a completed event", async () => {
    const { result } = renderHook(() => useChatStream("run-1"));
    act(() => FakeEventSource.last!.send({ i: 0, t: "completed", v: {} }));
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(FakeEventSource.last!.closed).toBe(true);
  });

  it("reconnects at the next index after a transport error", async () => {
    renderHook(() => useChatStream("run-1"));
    act(() =>
      FakeEventSource.last!.send({ i: 4, t: "text", v: { text: "a" } }),
    );
    act(() => FakeEventSource.last!.onerror?.());
    await waitFor(() =>
      expect(FakeEventSource.last!.url).toContain("offset=5"),
    );
  });

  it("surfaces a failed event as an error", async () => {
    const { result } = renderHook(() => useChatStream("run-1"));
    act(() =>
      FakeEventSource.last!.send({
        i: 0,
        t: "failed",
        v: { message: "boom", code: "X" },
      }),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.status).toBe("error");
  });

  it("does not connect when runId is null", () => {
    FakeEventSource.last = null;
    renderHook(() => useChatStream(null));
    expect(FakeEventSource.last).toBeNull();
  });
});
```

```python
# tests/api/test_stream_event_parity.py
import re
from pathlib import Path

from resume_tailor_harness.sessions.stream import (
    Completed, Failed, Notice, ReasoningDelta, TextDelta, ToolCompleted, ToolStarted,
)

_EVENTS = (TextDelta, ReasoningDelta, ToolStarted, ToolCompleted, Notice, Completed, Failed)


def test_typescript_tags_match_the_python_events():
    """The SSE body is invisible to OpenAPI, so this is the only drift gate."""
    source = Path("web/src/lib/chat/events.ts").read_text(encoding="utf-8")
    block = re.search(r"STREAM_EVENT_TAGS\s*=\s*\[(.*?)\]", source, re.S)
    assert block, "STREAM_EVENT_TAGS not found in events.ts"
    ts_tags = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert ts_tags == {event.tag for event in _EVENTS}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/lib/chat` then `.venv/Scripts/python.exe -m pytest tests/api/test_stream_event_parity.py -v`
Expected: FAIL — module not found / file not found

- [ ] **Step 3: Write the implementation**

```typescript
// web/src/lib/chat/events.ts
/**
 * Wire types for a conversational run's SSE stream.
 *
 * Hand-written on purpose: OpenAPI cannot describe an SSE event body, so these
 * never appear in contracts/ts/api.ts. tests/api/test_stream_event_parity.py is
 * the drift gate against the Python dataclasses in sessions/stream.py.
 */

export const STREAM_EVENT_TAGS = [
  "text",
  "reasoning",
  "tool_started",
  "tool_completed",
  "notice",
  "completed",
  "failed",
] as const;

export type StreamEventTag = (typeof STREAM_EVENT_TAGS)[number];

export type StreamEvent =
  | { i: number; t: "text"; v: { text: string } }
  | { i: number; t: "reasoning"; v: { text: string } }
  | { i: number; t: "tool_started"; v: { name: string; argsPreview: string } }
  | {
      i: number;
      t: "tool_completed";
      v: { name: string; resultPreview: string; ok: boolean };
    }
  | { i: number; t: "notice"; v: { message: string } }
  | { i: number; t: "completed"; v: Record<string, never> }
  | { i: number; t: "failed"; v: { message: string; code: string } };

export type ChatPart =
  | { kind: "text"; text: string }
  | { kind: "reasoning"; text: string }
  | {
      kind: "tool";
      name: string;
      argsPreview: string;
      resultPreview: string;
      ok: boolean;
      done: boolean;
    }
  | { kind: "notice"; message: string };

/**
 * Fold one event into the parts list.
 *
 * Consecutive deltas of the same kind merge into the trailing part; anything
 * else starts a new one, which is what preserves arrival order when a tool call
 * interrupts prose. Returns a new array — callers hold it in React state.
 */
export function reduceEvent(parts: ChatPart[], event: StreamEvent): ChatPart[] {
  const last = parts[parts.length - 1];
  switch (event.t) {
    case "text":
    case "reasoning": {
      const kind = event.t === "text" ? "text" : "reasoning";
      if (last && last.kind === kind) {
        return [
          ...parts.slice(0, -1),
          { kind, text: last.text + event.v.text },
        ];
      }
      return [...parts, { kind, text: event.v.text }];
    }
    case "tool_started":
      return [
        ...parts,
        {
          kind: "tool",
          name: event.v.name,
          argsPreview: event.v.argsPreview,
          resultPreview: "",
          ok: true,
          done: false,
        },
      ];
    case "tool_completed": {
      const index = parts.findLastIndex(
        (p) => p.kind === "tool" && !p.done && p.name === event.v.name,
      );
      if (index === -1) return parts;
      const next = [...parts];
      next[index] = {
        kind: "tool",
        name: event.v.name,
        argsPreview: (parts[index] as { argsPreview: string }).argsPreview,
        resultPreview: event.v.resultPreview,
        ok: event.v.ok,
        done: true,
      };
      return next;
    }
    case "notice":
      return [...parts, { kind: "notice", message: event.v.message }];
    default:
      return parts;
  }
}
```

```typescript
// web/src/lib/chat/useChatStream.ts
import { useCallback, useEffect, useRef, useState } from "react";

import { api, getToken, unwrap, withTokenParam } from "@/lib/api/client";
import { reduceEvent, type ChatPart, type StreamEvent } from "./events";

export type ChatStreamStatus = "idle" | "streaming" | "done" | "error";

/**
 * Subscribe to a conversational run's token stream.
 *
 * Tracks the highest index seen so a transport drop (or a page refresh, via the
 * caller persisting nothing — the backend log is the source of truth) reconnects
 * at `offset = lastIndex + 1` and replays only what was missed.
 */
export function useChatStream(runId: string | null) {
  const [parts, setParts] = useState<ChatPart[]>([]);
  const [status, setStatus] = useState<ChatStreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef(0);
  const source = useRef<EventSource | null>(null);

  const reset = useCallback(() => {
    setParts([]);
    setStatus("idle");
    setError(null);
    cursor.current = 0;
  }, []);

  const stop = useCallback(() => {
    source.current?.close();
    source.current = null;
    if (runId)
      void unwrap(
        api.POST("/api/runs/{run_id}/cancel", {
          params: { path: { run_id: runId } },
        }),
      );
    setStatus("done");
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let closed = false;

    const connect = (token?: string) => {
      if (closed) return;
      const base = `/api/runs/${runId}/stream?offset=${cursor.current}`;
      const url = token
        ? `${base}&token=${encodeURIComponent(token)}`
        : withTokenParam(base);
      const es = new EventSource(url);
      source.current = es;
      setStatus("streaming");

      es.onmessage = (e) => {
        let event: StreamEvent;
        try {
          event = JSON.parse(e.data) as StreamEvent;
        } catch {
          return;
        }
        cursor.current = Math.max(cursor.current, event.i + 1);
        if (event.t === "completed") {
          es.close();
          setStatus("done");
          return;
        }
        if (event.t === "failed") {
          es.close();
          setError(event.v.message);
          setStatus("error");
          return;
        }
        setParts((current) => reduceEvent(current, event));
      };

      es.onerror = () => {
        es.close();
        if (!closed) setTimeout(() => connect(token), 500);
      };
    };

    if (getToken()) connect();
    else {
      void unwrap(
        api.POST("/api/auth/link-token", { body: { purpose: "sse" } }),
      )
        .then((link) => connect(link.token))
        .catch(() => connect());
    }

    return () => {
      closed = true;
      source.current?.close();
      source.current = null;
    };
  }, [runId]);

  return { parts, status, error, stop, reset };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/lib/chat` and `.venv/Scripts/python.exe -m pytest tests/api/test_stream_event_parity.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
cd web && npm run lint && cd ..
git add web/src/lib/chat tests/api/test_stream_event_parity.py
git commit -m "feat(web): add chat stream types, reducer, and useChatStream"
```

---

## Task 10: Chat primitives

**Files:**

- Create: `web/src/components/chat/ChatThread.tsx`, `ChatMessage.tsx`, `ChatComposer.tsx`, `parts/TextPart.tsx`, `parts/ToolPart.tsx`, `parts/ReasoningPart.tsx`, `parts/NoticePart.tsx`, `ChatThread.test.tsx`

**Interfaces:**

- Consumes: `ChatPart` from Task 9.
- Produces: `<ChatThread messages={ChatThreadMessage[]} streaming={ChatPart[] | null} showReasoning?: boolean />`; `ChatThreadMessage = { id: string; role: "user" | "assistant"; parts: ChatPart[] }`; `<ChatComposer value onChange onSend onStop busy placeholder />`.

**Design rule:** autoscroll only while the viewport is "stuck" (within 64px of the bottom). Release permanently on an upward scroll and show a jump-to-latest pill. Never call `scrollIntoView` per token.

- [ ] **Step 1: Write the failing tests**

```tsx
// web/src/components/chat/ChatThread.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatThread } from "./ChatThread";

const message = (id: string, role: "user" | "assistant", text: string) => ({
  id,
  role,
  parts: [{ kind: "text" as const, text }],
});

describe("ChatThread", () => {
  it("renders messages in order", () => {
    render(
      <ChatThread
        messages={[
          message("1", "user", "hi"),
          message("2", "assistant", "hello"),
        ]}
        streaming={null}
      />,
    );
    const bubbles = screen.getAllByTestId("chat-message");
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0]).toHaveTextContent("hi");
  });

  it("renders parts in arrival order within a message", () => {
    render(
      <ChatThread
        messages={[]}
        streaming={[
          { kind: "text", text: "a" },
          {
            kind: "tool",
            name: "search",
            argsPreview: "x",
            resultPreview: "",
            ok: true,
            done: false,
          },
          { kind: "text", text: "b" },
        ]}
      />,
    );
    const parts = screen.getAllByTestId(/chat-part-/);
    expect(parts.map((p) => p.dataset.testid)).toEqual([
      "chat-part-text",
      "chat-part-tool",
      "chat-part-text",
    ]);
  });

  it("hides reasoning parts when showReasoning is false", () => {
    render(
      <ChatThread
        messages={[]}
        streaming={[{ kind: "reasoning", text: "secret" }]}
        showReasoning={false}
      />,
    );
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("shows reasoning parts when showReasoning is true", () => {
    render(
      <ChatThread
        messages={[]}
        streaming={[{ kind: "reasoning", text: "shown" }]}
        showReasoning
      />,
    );
    expect(screen.getByTestId("chat-part-reasoning")).toBeInTheDocument();
  });

  it("renders a notice part", () => {
    render(
      <ChatThread
        messages={[]}
        streaming={[{ kind: "notice", message: "not attached" }]}
      />,
    );
    expect(screen.getByText(/not attached/)).toBeInTheDocument();
  });

  it("shows the jump-to-latest pill after the user scrolls up", () => {
    render(
      <ChatThread
        messages={[message("1", "assistant", "hi")]}
        streaming={null}
      />,
    );
    const viewport = screen.getByTestId("chat-viewport");
    Object.defineProperty(viewport, "scrollHeight", {
      value: 1000,
      configurable: true,
    });
    Object.defineProperty(viewport, "clientHeight", {
      value: 200,
      configurable: true,
    });
    Object.defineProperty(viewport, "scrollTop", {
      value: 100,
      configurable: true,
      writable: true,
    });
    fireEvent.scroll(viewport);
    expect(
      screen.getByRole("button", { name: /jump to latest/i }),
    ).toBeInTheDocument();
  });

  it("hides the pill once the user is back at the bottom", () => {
    render(
      <ChatThread
        messages={[message("1", "assistant", "hi")]}
        streaming={null}
      />,
    );
    const viewport = screen.getByTestId("chat-viewport");
    Object.defineProperty(viewport, "scrollHeight", {
      value: 1000,
      configurable: true,
    });
    Object.defineProperty(viewport, "clientHeight", {
      value: 200,
      configurable: true,
    });
    Object.defineProperty(viewport, "scrollTop", {
      value: 100,
      configurable: true,
      writable: true,
    });
    fireEvent.scroll(viewport);
    (viewport as HTMLElement).scrollTop = 800;
    fireEvent.scroll(viewport);
    expect(
      screen.queryByRole("button", { name: /jump to latest/i }),
    ).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/components/chat`
Expected: FAIL — cannot resolve `./ChatThread`

- [ ] **Step 3: Write the implementation**

```tsx
// web/src/components/chat/ChatThread.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ChatPart } from "@/lib/chat/events";

import { ChatMessage } from "./ChatMessage";

export interface ChatThreadMessage {
  id: string;
  role: "user" | "assistant";
  parts: ChatPart[];
}

/** How close to the bottom still counts as "following along". */
const STICK_THRESHOLD_PX = 64;

/**
 * A scrolling transcript that follows new content only while the reader is at
 * the bottom.
 *
 * Force-scrolling on every token is the single most common chat-UI bug: it makes
 * scrolling back to re-read a previous answer impossible while a reply streams.
 * We track "stuck" state from scroll events and release it permanently on an
 * upward scroll, offering a pill instead.
 */
export function ChatThread({
  messages,
  streaming,
  showReasoning = true,
  className,
}: {
  messages: ChatThreadMessage[];
  streaming: ChatPart[] | null;
  showReasoning?: boolean;
  className?: string;
}) {
  const viewport = useRef<HTMLDivElement | null>(null);
  const [stuck, setStuck] = useState(true);

  const onScroll = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    const distance = node.scrollHeight - node.clientHeight - node.scrollTop;
    setStuck(distance <= STICK_THRESHOLD_PX);
  }, []);

  const jump = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    setStuck(true);
  }, []);

  useEffect(() => {
    if (!stuck) return;
    const node = viewport.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, streaming, stuck]);

  return (
    <div className={cn("relative min-h-0 flex-1", className)}>
      <div
        ref={viewport}
        data-testid="chat-viewport"
        onScroll={onScroll}
        className="h-full overflow-y-auto px-1"
      >
        <div className="space-y-4 py-2">
          {messages.map((message) => (
            <ChatMessage
              key={message.id}
              message={message}
              showReasoning={showReasoning}
            />
          ))}
          {streaming && streaming.length > 0 ? (
            <ChatMessage
              message={{ id: "streaming", role: "assistant", parts: streaming }}
              showReasoning={showReasoning}
              streaming
            />
          ) : null}
        </div>
      </div>
      {!stuck ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={jump}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md"
        >
          <ArrowDown className="size-4" />
          Jump to latest
        </Button>
      ) : null}
    </div>
  );
}
```

```tsx
// web/src/components/chat/ChatMessage.tsx
import { Bot, UserRound } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ChatPart } from "@/lib/chat/events";

import { NoticePart } from "./parts/NoticePart";
import { ReasoningPart } from "./parts/ReasoningPart";
import { TextPart } from "./parts/TextPart";
import { ToolPart } from "./parts/ToolPart";
import type { ChatThreadMessage } from "./ChatThread";

export function ChatMessage({
  message,
  showReasoning,
  streaming = false,
}: {
  message: ChatThreadMessage;
  showReasoning: boolean;
  streaming?: boolean;
}) {
  const assistant = message.role === "assistant";
  const visible = showReasoning
    ? message.parts
    : message.parts.filter((p) => p.kind !== "reasoning");
  return (
    <div
      data-testid="chat-message"
      className={cn("flex gap-3", assistant ? "" : "flex-row-reverse")}
    >
      <div className="mt-1 shrink-0 rounded-full bg-muted p-1.5">
        {assistant ? (
          <Bot className="size-4" />
        ) : (
          <UserRound className="size-4" />
        )}
      </div>
      <div
        className={cn(
          "min-w-0 max-w-[42rem] space-y-2 rounded-lg px-3 py-2 text-sm",
          assistant ? "bg-muted/50" : "bg-primary/10",
        )}
      >
        {visible.map((part, index) => {
          const key = `${message.id}-${index}`;
          if (part.kind === "text") {
            return (
              <TextPart
                key={key}
                text={part.text}
                caret={streaming && index === visible.length - 1}
              />
            );
          }
          if (part.kind === "tool") return <ToolPart key={key} part={part} />;
          if (part.kind === "reasoning")
            return <ReasoningPart key={key} text={part.text} />;
          return <NoticePart key={key} message={part.message} />;
        })}
      </div>
    </div>
  );
}
```

```tsx
// web/src/components/chat/parts/TextPart.tsx
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

/** Prose. The caret marks the live tail of a streaming reply. */
export function TextPart({
  text,
  caret = false,
}: {
  text: string;
  caret?: boolean;
}) {
  return (
    <div
      data-testid="chat-part-text"
      className="prose prose-sm dark:prose-invert max-w-none"
    >
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
        {text}
      </ReactMarkdown>
      {caret ? (
        <span
          aria-hidden
          className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-foreground align-text-bottom"
        />
      ) : null}
    </div>
  );
}
```

```tsx
// web/src/components/chat/parts/ToolPart.tsx
import { Check, Loader2, X } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { ChatPart } from "@/lib/chat/events";

type ToolChatPart = Extract<ChatPart, { kind: "tool" }>;

/** A tool call as a compact chip; the result expands on demand. */
export function ToolPart({ part }: { part: ToolChatPart }) {
  return (
    <Collapsible data-testid="chat-part-tool">
      <CollapsibleTrigger
        render={
          <button
            type="button"
            className="flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs text-muted-foreground"
          >
            {!part.done ? (
              <Loader2 className="size-3 animate-spin" />
            ) : part.ok ? (
              <Check className="size-3" />
            ) : (
              <X className="size-3 text-destructive" />
            )}
            <span className="font-medium">{part.name}</span>
            {part.argsPreview ? (
              <span className="truncate max-w-40">{part.argsPreview}</span>
            ) : null}
          </button>
        }
      />
      <CollapsibleContent className="mt-1 rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
        {part.resultPreview || "No result yet."}
      </CollapsibleContent>
    </Collapsible>
  );
}
```

```tsx
// web/src/components/chat/parts/ReasoningPart.tsx
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

/** Provider-exposed reasoning, collapsed by default. Never rendered in an interview. */
export function ReasoningPart({ text }: { text: string }) {
  return (
    <Collapsible data-testid="chat-part-reasoning">
      <CollapsibleTrigger
        render={
          <button
            type="button"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            Show reasoning
          </button>
        }
      />
      <CollapsibleContent className="mt-1 whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
        {text}
      </CollapsibleContent>
    </Collapsible>
  );
}
```

```tsx
// web/src/components/chat/parts/NoticePart.tsx
import { TriangleAlert } from "lucide-react";

/** A degradation notice, e.g. a draft note dropped by the quote gate. */
export function NoticePart({ message }: { message: string }) {
  return (
    <p
      data-testid="chat-part-notice"
      className="flex items-start gap-2 rounded-md bg-amber-500/10 p-2 text-xs text-amber-900 dark:text-amber-200"
    >
      <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
      <span>{message}</span>
    </p>
  );
}
```

```tsx
// web/src/components/chat/ChatComposer.tsx
import { Send, Square } from "lucide-react";

import { TranscribeButton } from "@/components/TranscribeButton";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/** Message input with a send/stop toggle. Enter sends; Shift+Enter newlines. */
export function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  placeholder = "Type your reply…",
}: {
  value: string;
  onChange: (next: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  placeholder?: string;
}) {
  return (
    <div className="flex items-end gap-2">
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={2}
        className="min-h-16 flex-1 resize-none"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!busy && value.trim()) onSend();
          }
        }}
      />
      <TranscribeButton
        onText={(text) => onChange(value ? `${value} ${text}` : text)}
      />
      {busy ? (
        <Button
          size="icon"
          variant="secondary"
          onClick={onStop}
          aria-label="Stop generating"
        >
          <Square className="size-4" />
        </Button>
      ) : (
        <Button
          size="icon"
          onClick={onSend}
          disabled={!value.trim()}
          aria-label="Send message"
        >
          <Send className="size-4" />
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/components/chat`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
cd web && npm run lint && cd ..
git add web/src/components/chat
git commit -m "feat(web): add shared chat thread primitives with scroll anchoring"
```

---

## Task 11: CoachPage on `<ChatThread>`

**Files:**

- Modify: `web/src/features/coach/CoachPage.tsx`, `web/src/features/coach/use-coach.ts`, `web/src/features/coach/CoachPage.test.tsx`

**Interfaces:**

- Consumes: `ChatThread`, `ChatComposer`, `useChatStream`.
- Produces: no new exports; `useSendCoachMessage` additionally returns the `runId` so the page can attach a stream.

- [ ] **Step 1: Write the failing tests**

```tsx
// append to web/src/features/coach/CoachPage.test.tsx
it("renders streamed text before the session refetch lands", async () => {
  renderCoachPage({ session: activeSession });
  await sendMessage("we cut p99 latency");
  emitStreamEvent({ i: 0, t: "text", v: { text: "Strong answer." } });
  expect(await screen.findByText("Strong answer.")).toBeInTheDocument();
});

it("replaces the streamed bubble with the durable turn without a gap", async () => {
  renderCoachPage({ session: activeSession });
  await sendMessage("answer");
  emitStreamEvent({ i: 0, t: "text", v: { text: "Streamed." } });
  emitStreamEvent({ i: 1, t: "completed", v: {} });
  resolveSessionRefetch({
    ...activeSession,
    turns: [...activeSession.turns, coachTurn("Streamed.")],
  });
  expect(screen.getAllByText("Streamed.")).toHaveLength(1);
});

it("shows a stop button while streaming and cancels the run", async () => {
  renderCoachPage({ session: activeSession });
  await sendMessage("answer");
  const stop = await screen.findByRole("button", { name: /stop generating/i });
  fireEvent.click(stop);
  expect(cancelSpy).toHaveBeenCalledWith(
    expect.objectContaining({ run_id: "run-1" }),
  );
});

it("renders a tool chip inline", async () => {
  renderCoachPage({ session: activeSession });
  await sendMessage("answer");
  emitStreamEvent({
    i: 0,
    t: "tool_started",
    v: { name: "search_corpus", argsPreview: "Kafka" },
  });
  expect(await screen.findByText("search_corpus")).toBeInTheDocument();
});

it("offers retry on the message when the stream fails", async () => {
  renderCoachPage({ session: activeSession });
  await sendMessage("answer");
  emitStreamEvent({
    i: 0,
    t: "failed",
    v: { message: "provider error", code: "X" },
  });
  expect(
    await screen.findByRole("button", { name: /retry/i }),
  ).toBeInTheDocument();
});

it("renders a persisted notice on a reloaded turn", async () => {
  renderCoachPage({
    session: {
      ...activeSession,
      turns: [
        coachTurnWithNotice(
          "Drafted.",
          "Note not attached — quote check failed.",
        ),
      ],
    },
  });
  expect(await screen.findByText(/quote check failed/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/coach`
Expected: FAIL — no stop button, streamed text never rendered

- [ ] **Step 3: Write the implementation**

In `use-coach.ts`, have `useSendCoachMessage` expose the started run id:

```typescript
export function useSendCoachMessage() {
  const [runId, setRunId] = useState<string | null>(null);
  const mutation = useMutation({
    /* existing body */
  });
  // in the existing onSuccess, before seedRun:
  //   setRunId(run.runId);
  return { ...mutation, runId, clearRun: () => setRunId(null) };
}
```

In `CoachPage.tsx`:

- Replace the hand-rolled transcript block with `<ChatThread>`, mapping each persisted turn to `ChatThreadMessage`:

```tsx
const messages: ChatThreadMessage[] = (session.data?.turns ?? []).map(
  (turn, index) => ({
    id: `${turn.at}-${index}`,
    role: turn.role === "coach" ? "assistant" : "user",
    parts: [
      { kind: "text", text: turn.text },
      ...(turn.notice
        ? [{ kind: "notice" as const, message: turn.notice }]
        : []),
    ],
  }),
);
```

- Attach the stream and hold the synthetic bubble until the refetch lands:

```tsx
const stream = useChatStream(send.runId);
const [pendingRun, setPendingRun] = useState<string | null>(null);

// The streamed bubble is dropped only after the durable turn arrives, so there
// is never a frame with both or neither.
const durableCount = session.data?.turns?.length ?? 0;
const priorCount = useRef(durableCount);
useEffect(() => {
  if (stream.status === "done" && durableCount > priorCount.current) {
    stream.reset();
    send.clearRun();
    setPendingRun(null);
  }
  priorCount.current = Math.max(priorCount.current, durableCount);
}, [stream.status, durableCount]);

<ChatThread
  messages={messages}
  streaming={send.runId ? stream.parts : null}
  showReasoning
/>;
```

- Replace the send row with `<ChatComposer ... busy={stream.status === "streaming"} onStop={stream.stop} />`.
- Render the in-place retry when `stream.status === "error"`: a small row beneath the streamed bubble with the error text and a Retry button that re-sends `lastMessage`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/coach`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

```bash
cd web && npm run lint && npx tsc --noEmit && cd ..
git add web/src/features/coach
git commit -m "feat(web): stream the coach transcript with stop and in-place retry"
```

---

## Task 12: InterviewPage on `<ChatThread>`

**Files:**

- Modify: `web/src/features/interview/InterviewPage.tsx`, `web/src/features/interview/use-interview.ts`, `web/src/features/interview/InterviewPage.test.tsx`

**Interfaces:**

- Consumes: everything from Tasks 9-11.
- Produces: no new exports.

**The one difference from Task 11:** `showReasoning={false}`. The interviewer stays in character; exposing its reasoning would tell the candidate what the question is probing for.

- [ ] **Step 1: Write the failing tests**

```tsx
// append to web/src/features/interview/InterviewPage.test.tsx
it("streams the interviewer's question", async () => {
  renderInterviewPage({ session: activeInterview });
  await sendAnswer("I owned the migration.");
  emitStreamEvent({
    i: 0,
    t: "text",
    v: { text: "Walk me through the rollback." },
  });
  expect(await screen.findByText(/rollback/)).toBeInTheDocument();
});

it("never renders the interviewer's reasoning", async () => {
  renderInterviewPage({ session: activeInterview });
  await sendAnswer("answer");
  emitStreamEvent({
    i: 0,
    t: "reasoning",
    v: { text: "probing for ownership" },
  });
  expect(screen.queryByText(/probing for ownership/)).not.toBeInTheDocument();
  expect(screen.queryByTestId("chat-part-reasoning")).not.toBeInTheDocument();
});

it("still renders tool chips in an interview", async () => {
  renderInterviewPage({ session: activeInterview });
  await sendAnswer("answer");
  emitStreamEvent({
    i: 0,
    t: "tool_started",
    v: { name: "read_jd", argsPreview: "" },
  });
  expect(await screen.findByText("read_jd")).toBeInTheDocument();
});

it("shows a stop button during an interview turn", async () => {
  renderInterviewPage({ session: activeInterview });
  await sendAnswer("answer");
  expect(
    await screen.findByRole("button", { name: /stop generating/i }),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/interview`
Expected: FAIL — streamed text never rendered

- [ ] **Step 3: Write the implementation**

Apply the Task 11 changes to `InterviewPage.tsx` and `use-interview.ts` verbatim, with two differences:

- `<ChatThread ... showReasoning={false} />`
- Map turns with `turn.role === "interviewer" ? "assistant" : "user"`, and include `turn.notice` as a notice part exactly as the coach does.

Leave the debrief panel, `SessionsRail`, `InterviewSetupDialog`, and `ActiveInterviewBanner` untouched — the debrief is not a streamed turn.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/interview`
Expected: all PASS

- [ ] **Step 5: Full verification, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest
ruff check
cd web && npm run lint && npx tsc --noEmit && npm test -- --run && cd ..
git add web/src/features/interview
git commit -m "feat(web): stream the interview transcript with reasoning suppressed"
```

- [ ] **Step 6: Manual smoke check**

Start the API with `resume-tailor-harness serve`, open the Coach page, send a message, and confirm: text appears incrementally; a tool chip appears and resolves; refreshing mid-turn resumes the partial answer rather than losing it; Stop halts generation and leaves the transcript unchanged; setting `STREAM_ENABLED=false` restores the blocking behavior.

---

## Self-Review

**Spec coverage:**

| Spec section                                                    | Task   |
| --------------------------------------------------------------- | ------ |
| §1 streaming seam in `llm_runner`                               | 2      |
| §2 sink protocol, three sinks                                   | 1      |
| §3 SSE reader with offset                                       | 7      |
| §4 delimiter, holdback, prose authoritative                     | 3, 5   |
| §5 `stream_enabled` kill switch                                 | 5      |
| Validation split, `DraftRejected`, durable notices              | 4      |
| Coach streams (opening/message/recap)                           | 5      |
| Interview streams; debrief does not                             | 6      |
| CLI console sink                                                | 8      |
| Chat primitives, parts model, anchoring                         | 10     |
| Stop, jump-to-latest, tool/reasoning disclosure, in-place retry | 10, 11 |
| Interviewer reasoning suppressed                                | 12     |
| Contracts + parity test                                         | 9      |
| Bubble lifecycle without flicker                                | 11     |

No gaps.

**Placeholder scan:** none — every step carries runnable code or an exact command.

**Type consistency:** `StreamEvent` tags (`text`, `reasoning`, `tool_started`, `tool_completed`, `notice`, `completed`, `failed`) are identical in Task 1 (Python), Task 9 (TypeScript), and the parity test. `format_with_retry`'s `validate(formatted, strict)` two-argument form is defined in Task 4 and used by Tasks 5 and 6. `persona_output` is introduced in Task 5 as a private helper and promoted to `sessions/turns.py` in Task 6 — Task 6 states this explicitly so the move is not a surprise. `ChatPart` and `ChatThreadMessage` are defined in Tasks 9 and 10 and consumed unchanged in 11 and 12.
