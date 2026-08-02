"""Provider-neutral conversational stream events and sinks."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, TextIO


@dataclass(frozen=True)
class TextDelta:
    text: str
    tag: ClassVar[str] = "text"

    def payload(self) -> dict[str, object]:
        return {"text": self.text}


@dataclass(frozen=True)
class ReasoningDelta:
    text: str
    tag: ClassVar[str] = "reasoning"

    def payload(self) -> dict[str, object]:
        return {"text": self.text}


@dataclass(frozen=True)
class ToolStarted:
    call_id: str
    name: str
    args_preview: str = ""
    tag: ClassVar[str] = "tool_started"

    def payload(self) -> dict[str, object]:
        return {
            "callId": self.call_id,
            "name": self.name,
            "argsPreview": self.args_preview,
        }


@dataclass(frozen=True)
class ToolCompleted:
    call_id: str
    name: str
    result_preview: str = ""
    ok: bool = True
    tag: ClassVar[str] = "tool_completed"

    def payload(self) -> dict[str, object]:
        return {
            "callId": self.call_id,
            "name": self.name,
            "resultPreview": self.result_preview,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class Notice:
    message: str
    tag: ClassVar[str] = "notice"

    def payload(self) -> dict[str, object]:
        return {"message": self.message}


@dataclass(frozen=True)
class Settled:
    """The visible reply is complete while post-processing may continue."""

    tag: ClassVar[str] = "settled"

    def payload(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True)
class Completed:
    """Internal success terminal; ``response`` is never serialized to clients."""

    response: Any | None = field(default=None, compare=False, repr=False)
    tag: ClassVar[str] = "completed"

    def payload(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True)
class Failed:
    message: str
    code: str = "STREAM_ERROR"
    tag: ClassVar[str] = "failed"

    def payload(self) -> dict[str, object]:
        return {"message": self.message, "code": self.code}


StreamEvent = (
    TextDelta
    | ReasoningDelta
    | ToolStarted
    | ToolCompleted
    | Notice
    | Settled
    | Completed
    | Failed
)
TERMINAL_TAGS = frozenset({Completed.tag, Failed.tag})


def encode_event(index: int, event: StreamEvent) -> str:
    """Encode one event as a single NDJSON row without a trailing newline."""
    return json.dumps(
        {"i": index, "t": event.tag, "v": event.payload()},
        ensure_ascii=False,
        separators=(",", ":"),
    )


class StreamSink(Protocol):
    def emit(self, event: StreamEvent) -> None: ...

    def close(self) -> None: ...


class NullSink:
    def emit(self, event: StreamEvent) -> None:
        return None

    def close(self) -> None:
        return None


class ConsoleStreamSink:
    """Render visible stream events to a terminal writer."""

    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self._closed = False

    def emit(self, event: StreamEvent) -> None:
        if self._closed:
            return
        if isinstance(event, TextDelta):
            self._write(event.text)
        elif isinstance(event, ToolStarted):
            detail = f" {event.args_preview}" if event.args_preview else ""
            self._write(f"\n  [{event.name}{detail}]\n")
        elif isinstance(event, (Notice, Failed)):
            self._write(f"\n  ! {event.message}\n")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._write("\n")


class RunStreamSink:
    """Batch prose deltas and append ordered events to a run-owned NDJSON file.

    Text and reasoning are both token streams and are batched on the same
    budget. Reasoning used to bypass batching, which cost one file
    open/write/flush and one SSE frame per token: a live DeepSeek coach turn
    emitted 1,846 reasoning deltas against 14 batched text rows, and every one
    of those frames drove a React re-render that re-parsed the thread's
    markdown. The two streams are batched *separately* -- reasoning hides
    behind a disclosure while text is the reply -- so a kind change flushes
    whatever is pending before it starts a new batch. A deterministic 120-delta
    run (15 chars every 10 ms) produced 15 rows at 80 ms / 240 chars, 30 at
    40 ms / 120 chars, and 58 at 20 ms / 60 chars; 40/120 halves median batch
    latency (40 ms to 20 ms) while capping event growth at 2x.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        flush_interval: float = 0.04,
        flush_chars: int = 120,
        on_append: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._flush_interval = flush_interval
        self._flush_chars = flush_chars
        self._on_append = on_append
        self._clock = clock
        self._index = 0
        self._pending: list[str] = []
        self._pending_len = 0
        self._pending_kind: type[TextDelta | ReasoningDelta] = TextDelta
        self._last_flush = self._clock()
        self._terminal = False
        self._closed = False
        self._handle: TextIO | None = None

    def emit(self, event: StreamEvent) -> None:
        if self._closed or self._terminal:
            return
        if isinstance(event, (TextDelta, ReasoningDelta)):
            if type(event) is not self._pending_kind:
                self._flush_pending()
                self._pending_kind = type(event)
            self._pending.append(event.text)
            self._pending_len += len(event.text)
            flush_due = self._clock() - self._last_flush >= self._flush_interval
            if self._pending_len >= self._flush_chars or flush_due:
                self._flush_pending()
            return
        self._flush_pending()
        self._append(event)
        if event.tag in TERMINAL_TAGS:
            self._terminal = True

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        text = "".join(self._pending)
        self._pending.clear()
        self._pending_len = 0
        self._last_flush = self._clock()
        self._append(self._pending_kind(text))

    def _append(self, event: StreamEvent) -> None:
        line = encode_event(self._index, event)
        self._index += 1
        if self._handle is None:
            self._handle = self._path.open("a", encoding="utf-8")
        self._handle.write(line + "\n")
        self._handle.flush()
        if self._on_append is not None:
            self._on_append()

    def close(self) -> None:
        if self._closed:
            return
        if not self._terminal:
            self._flush_pending()
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self._closed = True


def _parse_rows(text: str, offset: int) -> Iterator[tuple[int, str, dict]]:
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        index = row.get("i")
        tag = row.get("t")
        payload = row.get("v")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < max(offset, 0)
            or not isinstance(tag, str)
            or not tag
            or not isinstance(payload, dict)
        ):
            continue
        yield index, tag, payload


def read_stream(path: Path | str, offset: int = 0) -> Iterator[tuple[int, str, dict]]:
    """Read complete, well-shaped rows with indexes at or beyond ``offset``."""
    file_path = Path(path)
    if not file_path.is_file():
        return
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError:
        return
    yield from _parse_rows(raw, offset)


class StreamTail:
    """Poll-friendly cursor that only re-reads bytes appended since its last read.

    ``read_stream`` re-reads and re-parses the whole file every call, which is
    wasteful on a hot poll loop (``stream_events`` calls it every
    ``poll_interval`` for a run's full duration). This tracks the raw byte
    position already consumed and seeks there instead, so each poll only pays
    for the newly appended tail. It always stops at the last complete
    newline, so a line still mid-``flush()`` is left for the next read rather
    than parsed as a truncated row.
    """

    def __init__(self, path: Path | str, byte_pos: int = 0) -> None:
        self._path = Path(path)
        self._byte_pos = byte_pos

    def read(self, offset: int = 0) -> list[tuple[int, str, dict]]:
        try:
            with self._path.open("rb") as handle:
                handle.seek(self._byte_pos)
                chunk = handle.read()
        except OSError:
            return []
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            return []
        complete = chunk[: last_newline + 1]
        self._byte_pos += len(complete)
        return list(_parse_rows(complete.decode("utf-8"), offset))
