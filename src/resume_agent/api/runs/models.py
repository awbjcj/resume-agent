"""Validated in-memory view of file-backed background runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from resume_agent.progress import progress_stats


class RunState(StrEnum):
    pending = "pending"
    running = "running"
    cancelling = "cancelling"
    done = "done"
    error = "error"
    cancelled = "cancelled"


ACTIVE_RUN_STATES = frozenset({RunState.pending, RunState.running, RunState.cancelling})
TERMINAL_RUN_STATES = frozenset({RunState.done, RunState.error, RunState.cancelled})


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    kind: str
    state: RunState
    label: str
    current: int
    total: int
    created_at: datetime
    phase_started_at: datetime
    updated_at: datetime
    percent: int
    eta_text: str | None
    result: Any | None
    error: str | None
    user_id: str | None = None
    error_code: str | None = None
    phase_index: int | None = None
    phase_count: int | None = None
    meta: dict[str, Any] | None = None


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _counter(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def parse_run_snapshot(run_id: str, raw: object) -> RunSnapshot | None:
    """Project untrusted JSON into a typed run snapshot, or reject it."""
    if not isinstance(raw, Mapping):
        return None
    try:
        state = RunState(raw.get("state"))
    except (TypeError, ValueError):
        return None
    kind = raw.get("kind")
    current = _counter(raw.get("current"))
    total = _counter(raw.get("total"))
    phase_started_at = _aware_datetime(raw.get("started_at"))
    created_at = _aware_datetime(raw.get("created_at")) or phase_started_at
    updated_at = _aware_datetime(raw.get("updated_at"))
    if (
        not isinstance(kind, str)
        or not kind.strip()
        or current is None
        or total is None
        or created_at is None
        or phase_started_at is None
        or updated_at is None
    ):
        return None

    normalized = dict(raw)
    normalized["process"] = run_id
    stats = progress_stats(normalized)
    label = raw.get("label")
    error = raw.get("error")
    user_id = raw.get("user_id")
    error_code = raw.get("error_code")
    raw_meta = raw.get("meta")
    meta = dict(raw_meta) if isinstance(raw_meta, Mapping) else None
    return RunSnapshot(
        run_id=run_id,
        kind=kind.strip(),
        state=state,
        label=label.strip()
        if isinstance(label, str) and label.strip()
        else kind.strip(),
        current=current,
        total=total,
        created_at=created_at,
        phase_started_at=phase_started_at,
        updated_at=updated_at,
        percent=stats.pct,
        eta_text=stats.eta_text,
        result=raw.get("result"),
        error=error if isinstance(error, str) else None,
        user_id=user_id if isinstance(user_id, str) else None,
        error_code=error_code if isinstance(error_code, str) else None,
        phase_index=_optional_positive_int(raw.get("phase_index")),
        phase_count=_optional_positive_int(raw.get("phase_count")),
        meta=meta,
    )
