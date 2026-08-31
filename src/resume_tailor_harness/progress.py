"""Cross-process progress channel for long-running commands.

CLI commands and API background runs execute outside the web request/response
loop. To show live progress, the running command writes a small JSON record and
readers poll it or stream it over SSE. Process-keyed CLI records live under
``data/progress/{name}.json``; run-keyed API records live under ``data/runs/``.

Mirrors ``discovery/connectors/telemetry.py`` — pure file IO, no third-party deps,
so the writer side is testable without a server and the reader side without a
running command.
"""

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor_harness.security.paths import confined_path

PROGRESS_ROOT = Path("data/progress")

#: Where the API persists one JSON record per background run (run_id-keyed).
RUNS_ROOT = Path("data/runs")

#: Legacy process-keyed progress emitters.
PROCESSES = ("pull", "discover", "tailor")

#: Throttle ``step`` writes to at most one per this many seconds (begin/done and
#: the final step always write regardless, so the bar never stalls short of 100%).
_MIN_WRITE_INTERVAL = 0.25

#: How long a finished (done/error) record keeps showing before the bar collapses.
TERMINAL_TTL_SECONDS = 60


def _path(process: str, root: Path | str = PROGRESS_ROOT) -> Path:
    return confined_path(root, f"{process}.json")


def atomic_write_text(path: Path, text: str, *, root: Path | str) -> None:
    """Write ``text`` to ``path`` so a concurrent reader never sees a torn file.

    ``Path.write_text`` truncates-then-writes, so a reader polling mid-write can
    observe an empty/partial file — which :func:`read_progress` (and the SSE
    ``run_events`` consumer) then has to treat as a missing record. Writing to a
    sibling temp file and :func:`os.replace`-ing it in is atomic on POSIX and
    Windows, so readers always see either the previous or the next *complete*
    record. ``root`` is required so the temporary-file and replace capability
    cannot be redirected outside the owning workspace.
    """
    path = confined_path(root, Path(path).resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        for attempt in range(_WRITE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except OSError:
                if attempt == _WRITE_RETRIES - 1:
                    raise
                time.sleep(_WRITE_BACKOFF_SECONDS)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: Bounded retry for a transient read failure (Windows ``os.replace``/``open``
#: sharing violation while a run is actively writing progress). Each attempt
#: backs off this long; total worst-case stall is tiny but enough to clear the
#: replace window.
_READ_RETRIES = 3
_READ_BACKOFF_SECONDS = 0.02
_WRITE_RETRIES = 3
_WRITE_BACKOFF_SECONDS = 0.02


def read_progress(process: str, root: Path | str = PROGRESS_ROOT) -> dict | None:
    """Return the latest record for one process, or None if it has never run.

    Distinguishes three cases that all used to collapse to None:

    * **Absent** (never ran) → None.
    * **Corrupt** (unparseable JSON) → None immediately; spinning would never help.
    * **Transiently unreadable** → the file exists but ``open`` lost a race with
      the writer's atomic :func:`os.replace` (a Windows sharing violation surfaces
      as ``PermissionError``/``OSError``). This is momentary, so we retry briefly
      rather than report the run missing. Reporting it missing is what made a live
      SSE/GET run-lookup gate 404 a perfectly healthy run.
    """
    try:
        p = _path(process, root)
    except ValueError:
        return None
    for attempt in range(_READ_RETRIES):
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        except OSError:
            if attempt == _READ_RETRIES - 1:
                return None
            time.sleep(_READ_BACKOFF_SECONDS)
    return None


def read_all(root: Path | str = PROGRESS_ROOT) -> dict[str, dict]:
    """Return ``{process: record}`` for every process that has a record."""
    out: dict[str, dict] = {}
    for name in PROCESSES:
        record = read_progress(name, root)
        if record is not None:
            out[name] = record
    return out


def clear_progress(process: str, root: Path | str = PROGRESS_ROOT) -> None:
    """Remove a process's record (used to reset a stale bar)."""
    try:
        _path(process, root).unlink(missing_ok=True)
    except ValueError:
        return


class ProgressReporter:
    """Writes one process's live progress to its JSON file.

    Library and test callers pass ``None`` instead of a reporter, so the
    instrumented loops stay silent (and touch no disk) outside the CLI. A
    multi-phase process (discover) calls :meth:`begin` once per phase; ETA is
    therefore measured per phase, which is honest when each phase's total only
    becomes known as it starts.
    """

    def __init__(self, process: str, root: Path | str = PROGRESS_ROOT) -> None:
        _path(process, root)
        self.process = process
        self.root = Path(root)
        self._record: dict = {}
        self._last_write = 0.0

    def begin(
        self,
        total: int,
        label: str,
        *,
        phase_index: int | None = None,
        phase_count: int | None = None,
        **extra: object,
    ) -> None:
        """Start (or restart, for a new phase) the active progress segment."""
        self._record = {
            "process": self.process,
            "state": "running",
            "label": label,
            "phase_index": phase_index,
            "phase_count": phase_count,
            "current": 0,
            "total": total,
            "started_at": _now_iso(),
            **extra,
        }
        self._flush(force=True)

    def step(self, current: int, *, label: str | None = None, **extra: object) -> None:
        """Advance the active segment. No-op if :meth:`begin` was never called."""
        if not self._record:
            return
        self._record["current"] = current
        if label is not None:
            self._record["label"] = label
        self._record.update(extra)
        self._flush(force=current >= int(self._record.get("total") or 0))

    def checkpoint(self) -> None:
        """Raise when external cancellation is requested; base reporters never cancel."""

    def done(self, *, error: str | None = None, **extra: object) -> None:
        """Mark the process finished (``done``) or failed (``error``)."""
        if not self._record:
            # done() without begin() (e.g. nothing to process) — still emit a
            # terminal record so progress consumers can show completion.
            self._record = {
                "process": self.process,
                "label": self.process,
                "current": 0,
                "total": 0,
                "started_at": _now_iso(),
            }
        self._record["state"] = "error" if error else "done"
        self._record["error"] = error
        self._record.update(extra)
        self._flush(force=True)

    def cancelled(self, **extra: object) -> None:
        """Mark the process cancelled — a terminal state distinct from done/error.

        Partial work already committed is kept; the bar shows how far it got
        (``current``/``total`` are left untouched) with a cancelled badge.
        """
        if not self._record:
            self._record = {
                "process": self.process,
                "label": self.process,
                "current": 0,
                "total": 0,
                "started_at": _now_iso(),
            }
        self._record["state"] = "cancelled"
        self._record["error"] = None
        self._record.update(extra)
        self._flush(force=True)

    def _flush(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < _MIN_WRITE_INTERVAL:
            return
        self._last_write = now
        self._record["updated_at"] = _now_iso()
        atomic_write_text(
            _path(self.process, self.root),
            json.dumps(self._record, indent=2),
            root=self.root,
        )


@dataclass
class ProgressStats:
    """The display-ready view of a raw record: percentage, ETA, phase label."""

    process: str
    state: str  # running | done | error
    label: str
    pct: int  # 0..100
    current: int
    total: int
    phase: str | None  # "Phase 3 of 3", or None for single-phase processes
    eta_text: str | None  # "~2m left", or None when not estimable
    elapsed_text: str
    error: str | None


def _parse(ts: object) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _fmt_duration(seconds: float) -> str:
    total = int(max(0, seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def progress_stats(record: dict, *, now: datetime | None = None) -> ProgressStats:
    """Derive percentage, elapsed, and ETA from a raw progress record (pure).

    ETA assumes a steady per-item rate over the *current phase only* — measured
    from ``started_at`` to ``updated_at`` (which is when ``current`` was true),
    not to wall-clock now, so the rate is not skewed by reader poll lag.
    """
    now = now or datetime.now(timezone.utc)
    total = int(record.get("total") or 0)
    current = int(record.get("current") or 0)
    state = str(record.get("state") or "running")

    pct = 100 if state == "done" else (round(100 * current / total) if total > 0 else 0)
    pct = max(0, min(100, pct))

    phase_index = record.get("phase_index")
    phase_count = record.get("phase_count")
    phase = (
        f"Phase {phase_index} of {phase_count}" if phase_index and phase_count else None
    )

    started = _parse(record.get("started_at"))
    updated = _parse(record.get("updated_at")) or now
    elapsed = (updated - started).total_seconds() if started else 0.0

    eta_text: str | None = None
    if state == "running" and started and 0 < current < total:
        eta_text = _fmt_duration((elapsed / current) * (total - current))

    return ProgressStats(
        process=str(record.get("process") or ""),
        state=state,
        label=str(record.get("label") or record.get("process") or ""),
        pct=pct,
        current=current,
        total=total,
        phase=phase,
        eta_text=eta_text,
        elapsed_text=_fmt_duration(elapsed),
        error=record.get("error") if isinstance(record.get("error"), str) else None,
    )


def is_displayable(record: dict, *, now: datetime | None = None) -> bool:
    """Whether UI consumers should show this record.

    Running records always show; finished ones linger for ``TERMINAL_TTL_SECONDS``
    so a completed run gives a brief ✓/✕ confirmation before the bar collapses.
    """
    state = record.get("state")
    if state == "running":
        return True
    if state not in ("done", "error", "cancelled"):
        return False
    now = now or datetime.now(timezone.utc)
    updated = _parse(record.get("updated_at"))
    if updated is None:
        return False
    return (now - updated).total_seconds() <= TERMINAL_TTL_SECONDS
