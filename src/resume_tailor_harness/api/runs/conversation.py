"""Run wrapper that owns conversational stream terminal events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from resume_tailor_harness.api.runs.manager import RunCancelled, RunManager
from resume_tailor_harness.sessions.stream import Completed, Failed, RunStreamSink, StreamSink


def with_conversation_stream(
    manager: RunManager,
    work: Callable[[Any, StreamSink], object],
) -> Callable[[Any], object]:
    """Attach a run-owned sink and emit exactly one terminal event."""

    def wrapped(reporter):
        sink = RunStreamSink(
            manager.stream_path(reporter.run_id),
            on_append=manager.notifier(reporter.run_id).notify,
        )
        try:
            result = work(reporter, sink)
        except RunCancelled:
            sink.emit(Failed("Generation stopped.", "CANCELLED"))
            raise
        except Exception as exc:
            sink.emit(
                Failed(
                    str(exc) or type(exc).__name__,
                    getattr(exc, "code", None) or type(exc).__name__,
                )
            )
            raise
        else:
            sink.emit(Completed())
            return result
        finally:
            sink.close()

    return wrapped
