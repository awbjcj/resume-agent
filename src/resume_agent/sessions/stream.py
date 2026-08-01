"""Provider-neutral conversational stream events and sinks."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol


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
    TextDelta | ReasoningDelta | ToolStarted | ToolCompleted | Notice | Completed | Failed
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
    """Batch text deltas and append ordered events to a run-owned NDJSON file."""

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
        self._terminal = False
        self._closed = False

    def emit(self, event: StreamEvent) -> None:
        if self._closed or self._terminal:
            return
        if isinstance(event, TextDelta):
            self._pending.append(event.text)
            self._pending_len += len(event.text)
            flush_due = time.monotonic() - self._last_flush >= self._flush_interval
            if self._pending_len >= self._flush_chars or flush_due:
                self._flush_text()
            return
        self._flush_text()
        self._append(event)
        if event.tag in TERMINAL_TAGS:
            self._terminal = True

    def _flush_text(self) -> None:
        if not self._pending:
            return
        text = "".join(self._pending)
        self._pending.clear()
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
        if self._closed:
            return
        if not self._terminal:
            self._flush_text()
        self._closed = True


def read_stream(path: Path | str, offset: int = 0) -> Iterator[tuple[int, str, dict]]:
    """Read complete, well-shaped rows with indexes at or beyond ``offset``."""
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
