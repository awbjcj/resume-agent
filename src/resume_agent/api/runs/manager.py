"""Background run substrate.

A run is a unit of long work (discover/pull/tailor/cover-letter/add-job-from-url).
It is keyed by a uuid4 and persisted as one JSON record per run under RUNS_ROOT,
reusing ProgressReporter (so percent/ETA come for free). Work runs in an Executor
(a ThreadPool in production, an inline executor in tests). The worker callable
receives a ProgressReporter and returns a JSON-serializable result dict, which is
stamped onto the terminal record via reporter.done(result=...).

The worker must open its OWN DB session (a request's Session is not thread-safe),
so callables here are closures created by the run router with their own engine.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.progress import (
    RUNS_ROOT,
    ProgressReporter,
    atomic_write_text,
    clear_progress,
    read_progress,
)

RunFn = Callable[[ProgressReporter], object]


class RunProgressReporter(ProgressReporter):
    """ProgressReporter variant that preserves the run kind on every write."""

    def __init__(self, run_id: str, kind: str, root: Path | str) -> None:
        super().__init__(run_id, root=root)
        self.kind = kind

    def begin(
        self,
        total: int,
        label: str,
        *,
        phase_index: int | None = None,
        phase_count: int | None = None,
        **extra: object,
    ) -> None:
        super().begin(
            total,
            label,
            phase_index=phase_index,
            phase_count=phase_count,
            kind=self.kind,
            **extra,
        )

    def done(self, *, error: str | None = None, **extra: object) -> None:
        super().done(error=error, kind=self.kind, **extra)


class RunManager:
    def __init__(self, *, root: Path | str = RUNS_ROOT, executor: Executor | None = None) -> None:
        self.root = Path(root)
        self.executor = executor or ThreadPoolExecutor(max_workers=2)
        self._owns_executor = executor is None

    def create(self, kind: str) -> str:
        run_id = uuid.uuid4().hex
        # Seed a terminal-less "pending" record so GET works before work begins.
        self._write(run_id, {
            "process": run_id, "kind": kind, "state": "pending",
            "label": "Queued", "current": 0, "total": 0,
            "started_at": _now(), "result": None, "error": None,
            "updated_at": _now(),
        })
        return run_id

    def reporter(self, run_id: str, kind: str) -> RunProgressReporter:
        return RunProgressReporter(run_id, kind, self.root)

    def submit(self, kind: str, fn: RunFn) -> str:
        run_id = self.create(kind)
        reporter = self.reporter(run_id, kind)

        def _runner() -> None:
            try:
                result = fn(reporter)
                reporter.done(result=result)
            except Exception as exc:  # noqa: BLE001 — surface any failure as run error
                reporter.done(error=f"{type(exc).__name__}: {exc}", result=None)
            except BaseException as exc:  # interpreter exit/interrupt: still stamp, then re-raise
                reporter.done(error=f"{type(exc).__name__}: {exc}", result=None)
                raise

        self.executor.submit(_runner)
        return run_id

    def get(self, run_id: str) -> dict | None:
        return read_progress(run_id, root=self.root)

    def clear(self, run_id: str) -> None:
        clear_progress(run_id, root=self.root)

    def sweep(self, *, max_age_seconds: float = 86_400) -> int:
        """Delete run records whose file is older than max_age (default 1 day).

        Run files accumulate one-per-launch under RUNS_ROOT; without a sweep the
        directory grows unbounded on a long-lived server. Called on app startup.
        Returns the number of files removed.
        """
        if not self.root.exists():
            return 0
        cutoff = time.time() - max_age_seconds
        removed = 0
        for path in self.root.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def shutdown(self) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=False)

    def _write(self, run_id: str, record: dict) -> None:
        atomic_write_text(self.root / f"{run_id}.json", json.dumps(record, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
