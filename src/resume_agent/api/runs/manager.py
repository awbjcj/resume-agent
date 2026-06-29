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
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.api.runs.models import (
    ACTIVE_RUN_STATES,
    TERMINAL_RUN_STATES,
    RunSnapshot,
    parse_run_snapshot,
)
from resume_agent.progress import (
    RUNS_ROOT,
    ProgressReporter,
    atomic_write_text,
    clear_progress,
    read_progress,
)

RunFn = Callable[[ProgressReporter], object]


class RunCancelled(Exception):
    """Raised inside a worker when its run has been cancel-requested.

    Cooperative: only surfaces at a progress checkpoint (begin/step), so the
    worker stops cleanly between units of work rather than being killed
    mid-network-call. Caught by the runner, which stamps a ``cancelled`` record.
    """


class RunProgressReporter(ProgressReporter):
    """ProgressReporter variant that preserves the run kind on every write and
    is the cooperative-cancellation checkpoint: ``begin``/``step`` raise
    :class:`RunCancelled` once the run has been flagged for cancellation."""

    def __init__(
        self,
        run_id: str,
        kind: str,
        root: Path | str,
        *,
        created_at: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(run_id, root=root)
        self.kind = kind
        self.created_at = created_at or _now()
        self._cancel_check = cancel_check

    def _raise_if_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise RunCancelled

    def checkpoint(self) -> None:
        self._raise_if_cancelled()

    def begin(
        self,
        total: int,
        label: str,
        *,
        phase_index: int | None = None,
        phase_count: int | None = None,
        **extra: object,
    ) -> None:
        self._raise_if_cancelled()
        super().begin(
            total,
            label,
            phase_index=phase_index,
            phase_count=phase_count,
            kind=self.kind,
            created_at=self.created_at,
            **extra,
        )

    def step(self, current: int, *, label: str | None = None, **extra: object) -> None:
        self._raise_if_cancelled()
        super().step(current, label=label, **extra)

    def done(self, *, error: str | None = None, **extra: object) -> None:
        self._raise_if_cancelled()
        super().done(error=error, kind=self.kind, **extra)

    def cancelled(self, **extra: object) -> None:
        super().cancelled(kind=self.kind, **extra)


class RunManager:
    def __init__(
        self,
        *,
        root: Path | str = RUNS_ROOT,
        executor: Executor | None = None,
        kind_workers: dict[str, int] | None = None,
    ) -> None:
        self.root = Path(root)
        self.executor = executor or ThreadPoolExecutor(max_workers=2)
        self._owned_executors: list[Executor] = []
        if executor is None:
            self._owned_executors.append(self.executor)
        self._kind_executors = {
            kind: ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix=f"resume-agent-{kind}",
            )
            for kind, workers in (kind_workers or {}).items()
        }
        self._owned_executors.extend(self._kind_executors.values())
        # Run ids flagged for cooperative cancellation. A plain set is enough:
        # under the GIL add/discard/contains are atomic, and a missed read just
        # defers the stop to the next checkpoint.
        self._cancel_requested: set[str] = set()
        self._futures: dict[str, Future] = {}
        self._singleton_lock = threading.RLock()
        self._active_singletons: dict[str, str] = {}

    def request_cancel(self, run_id: str) -> bool:
        """Flag a run for cooperative cancellation.

        Returns False if the run is unknown or already terminal (nothing to
        cancel); True once flagged. The worker stops at its next checkpoint.
        """
        record = self._read_record(run_id)
        snapshot = parse_run_snapshot(run_id, record)
        if snapshot is None or snapshot.state in TERMINAL_RUN_STATES:
            return False
        assert record is not None
        self._cancel_requested.add(run_id)
        future = self._futures.get(run_id)
        if future is not None and future.cancel():
            record.update(state="cancelled", label="Cancelled", error=None, updated_at=_now())
            self._write(run_id, record)
            self._cancel_requested.discard(run_id)
            return True
        record.update(state="cancelling", label="Cancelling", updated_at=_now())
        self._write(run_id, record)
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        return run_id in self._cancel_requested

    def create(self, kind: str) -> str:
        run_id = uuid.uuid4().hex
        created_at = _now()
        # Seed a terminal-less "pending" record so GET works before work begins.
        self._write(run_id, {
            "process": run_id, "kind": kind, "state": "pending",
            "label": "Queued", "current": 0, "total": 0,
            "created_at": created_at, "started_at": created_at,
            "result": None, "error": None, "updated_at": created_at,
        })
        return run_id

    def reporter(self, run_id: str, kind: str) -> RunProgressReporter:
        record = self._read_record(run_id) or {}
        return RunProgressReporter(
            run_id,
            kind,
            self.root,
            created_at=str(record.get("created_at") or record.get("started_at") or _now()),
            cancel_check=lambda: self.is_cancel_requested(run_id),
        )

    def submit(
        self,
        kind: str,
        fn: RunFn,
        *,
        singleton_key: str | None = None,
    ) -> str:
        with self._singleton_lock:
            if singleton_key is not None:
                active_id = self._active_singletons.get(singleton_key)
                if active_id is not None:
                    snapshot = self.get(active_id)
                    if snapshot is not None and snapshot.state in ACTIVE_RUN_STATES:
                        return active_id
                    self._active_singletons.pop(singleton_key, None)

            run_id = self.create(kind)
            reporter = self.reporter(run_id, kind)
            if singleton_key is not None:
                self._active_singletons[singleton_key] = run_id

            def _runner() -> None:
                try:
                    result = fn(reporter)
                    reporter.done(result=result)
                except RunCancelled:  # cooperative stop — terminal but not a failure
                    reporter.cancelled()
                except Exception as exc:  # noqa: BLE001 — surface any failure as run error
                    reporter.done(error=f"{type(exc).__name__}: {exc}", result=None)
                except BaseException as exc:  # interpreter exit/interrupt: still stamp, then re-raise
                    reporter.done(error=f"{type(exc).__name__}: {exc}", result=None)
                    raise
                finally:
                    self._cancel_requested.discard(run_id)

            executor = self._kind_executors.get(kind, self.executor)
            try:
                future = executor.submit(_runner)
            except BaseException as exc:
                if singleton_key is not None:
                    self._active_singletons.pop(singleton_key, None)
                record = self._read_record(run_id)
                if record is not None:
                    record.update(
                        state="error",
                        label="Failed to start",
                        error=f"{type(exc).__name__}: {exc}",
                        updated_at=_now(),
                    )
                    self._write(run_id, record)
                raise
            self._futures[run_id] = future

            def release(_future: Future) -> None:
                with self._singleton_lock:
                    self._futures.pop(run_id, None)
                    if (
                        singleton_key is not None
                        and self._active_singletons.get(singleton_key) == run_id
                    ):
                        self._active_singletons.pop(singleton_key, None)

            future.add_done_callback(release)
        return run_id

    def _read_record(self, run_id: str) -> dict | None:
        return read_progress(run_id, root=self.root)

    def get(self, run_id: str) -> RunSnapshot | None:
        return parse_run_snapshot(run_id, self._read_record(run_id))

    def list_active(self) -> list[RunSnapshot]:
        if not self.root.exists():
            return []
        snapshots = [
            snapshot
            for path in self.root.glob("*.json")
            if (snapshot := self.get(path.stem)) is not None
            and snapshot.state in ACTIVE_RUN_STATES
        ]
        return sorted(snapshots, key=lambda item: (item.created_at, item.run_id))

    def recover_interrupted(self) -> int:
        if not self.root.exists():
            return 0
        recovered = 0
        for snapshot in self.list_active():
            record = self._read_record(snapshot.run_id)
            if record is None:
                continue
            record.update(
                state="error",
                label="Interrupted",
                error="Backend restarted before this run completed",
                updated_at=_now(),
            )
            self._write(snapshot.run_id, record)
            recovered += 1
        return recovered

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
        for executor in self._owned_executors:
            executor.shutdown(wait=False)

    def _write(self, run_id: str, record: dict) -> None:
        atomic_write_text(self.root / f"{run_id}.json", json.dumps(record, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
