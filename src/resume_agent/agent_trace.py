"""An append-only operational trace of the agent calls a run made.

``UsageEvent`` is a billing record. It answers "what did this cost?" and cannot
answer "what did this run *do*?" — there is no queryable per-run record of which
agent family produced which artifact, how many retries it took, how many tool
calls it made, or whether the prompt cache was hit. Diagnosing a slow or
expensive run therefore meant reading logs and guessing.

This is deliberately the smallest thing that closes that gap: one NDJSON file
per run, beside the run's own progress record, written with the same
append-flush durability pattern ``RunStreamSink`` uses. No schema, no table, no
API surface. Expand it only if it earns that.

**Operational events only.** A row carries counts, identities, and a terminal
status. It never carries prompt text, completion text, or reasoning content —
the same rule ``_map_stream_event`` enforces when it refuses to forward a
``reasoning_content`` equal to the visible answer.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_current: ContextVar[Path | None] = ContextVar("agent_trace_path", default=None)
_lock = threading.Lock()


@contextmanager
def agent_trace(path: Path | str | None) -> Iterator[Path | None]:
    """Direct agent-run rows to ``path`` for the duration of a run.

    Scoped through a ``ContextVar`` for the same reason the tenancy context is:
    ``RunManager.submit`` copies the caller's context into its worker, so a run
    started anywhere traces to its own directory without threading a handle
    through every agent builder.
    """
    resolved = Path(path) if path is not None else None
    token = _current.set(resolved)
    try:
        yield resolved
    finally:
        _current.reset(token)


def current_trace() -> Path | None:
    return _current.get()


def _metric(metrics: Any, name: str) -> int:
    value = getattr(metrics, name, None)
    if isinstance(value, (list, tuple)):
        value = sum(item or 0 for item in value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _tool_calls(response: Any) -> int:
    for name in ("tools", "tool_calls", "messages"):
        value = getattr(response, name, None)
        if isinstance(value, (list, tuple)):
            if name == "messages":
                return sum(1 for item in value if getattr(item, "tool_calls", None))
            return len(value)
    return 0


def record_agent_run(
    runner: Any,
    response: Any,
    *,
    retries: int = 0,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Append one operational row. Never raises; a trace is not the work."""
    path = _current.get()
    if path is None:
        return
    try:
        run_meta = getattr(runner, "run_meta", None)
        metrics = getattr(response, "metrics", None)
        skill_ref = getattr(run_meta, "skill_ref", None)
        family = getattr(run_meta, "agent_family", None)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run": path.stem.removesuffix(".agents"),
            "family": getattr(family, "value", family),
            "skill": str(skill_ref) if skill_ref is not None else None,
            "model": getattr(run_meta, "model_id", None),
            "retries": retries,
            "toolCalls": _tool_calls(response),
            "inputTokens": _metric(metrics, "input_tokens"),
            "outputTokens": _metric(metrics, "output_tokens"),
            "cacheReadTokens": _metric(metrics, "cache_read_tokens"),
            "cacheWriteTokens": _metric(metrics, "cache_write_tokens")
            or _metric(metrics, "cache_creation_tokens"),
            "reasoningTokens": _metric(metrics, "reasoning_tokens"),
            "status": status,
            "error": error,
        }
        line = json.dumps(row, default=str)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
    except Exception:  # noqa: BLE001 — a trace must never fail the run it traces
        logger.debug("agent trace write failed", exc_info=True)


def read_trace(path: Path | str) -> list[dict]:
    """Read a run's trace. A malformed row is skipped, never raised."""
    rows: list[dict] = []
    target = Path(path)
    if not target.exists():
        return rows
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows
