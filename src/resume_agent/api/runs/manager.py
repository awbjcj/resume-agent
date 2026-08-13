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
import contextvars
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.api.runs.models import (
    ACTIVE_RUN_STATES,
    TERMINAL_RUN_STATES,
    RunSnapshot,
    parse_run_snapshot,
)
from resume_agent.agent_trace import agent_trace
from resume_agent.api.runs.notify import StreamNotifier
from resume_agent.progress import (
    RUNS_ROOT,
    ProgressReporter,
    atomic_write_text,
    clear_progress,
    read_progress,
)
from resume_agent.tenancy.context import current_context

RunFn = Callable[[ProgressReporter], object]


class RunCancelled(Exception):
    """Raised inside a worker when its run has been cancel-requested.

    Cooperative: only surfaces at a progress checkpoint (begin/step), so the
    worker stops cleanly between units of work rather than being killed
    mid-network-call. Caught by the runner, which stamps a ``cancelled`` record.
    """


class RunQuotaError(RuntimeError):
    code = "QUOTA_EXCEEDED"


class RunSingletonConflict(RuntimeError):
    code = "CONFLICT"

    def __init__(self, run_id: str):
        super().__init__("A run is already active for this item")
        self.run_id = run_id


class RunResetConflict(RuntimeError):
    """A destructive workspace reset cannot proceed because runs are live.

    Raised either when the owner already has active runs, or when a reset for
    the same owner is already underway. Reusing ``RUNS_ACTIVE`` keeps the
    existing API contract for the caller.
    """

    code = "RUNS_ACTIVE"


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
        user_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        meta: dict[str, object] | None = None,
        notify: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(run_id, root=root)
        self.run_id = run_id
        self.kind = kind
        self.created_at = created_at or _now()
        self.user_id = user_id
        self._cancel_check = cancel_check
        self.meta = meta
        # Wakes SSE subscribers after a progress write lands. The durable JSON
        # record remains the source of truth; this only removes the poll delay
        # between the write and a client seeing it.
        self._notify = notify

    def _wake(self) -> None:
        if self._notify is not None:
            self._notify()

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
            user_id=self.user_id,
            meta=self.meta,
            **extra,
        )
        self._wake()

    def step(self, current: int, *, label: str | None = None, **extra: object) -> None:
        self._raise_if_cancelled()
        super().step(current, label=label, **extra)
        self._wake()

    def done(self, *, error: str | None = None, **extra: object) -> None:
        self._raise_if_cancelled()
        super().done(
            error=error,
            kind=self.kind,
            created_at=self.created_at,
            user_id=self.user_id,
            meta=self.meta,
            **extra,
        )
        self._wake()

    def cancelled(self, **extra: object) -> None:
        super().cancelled(
            kind=self.kind,
            created_at=self.created_at,
            user_id=self.user_id,
            meta=self.meta,
            **extra,
        )
        self._wake()


class RunManager:
    def __init__(
        self,
        *,
        root: Path | str = RUNS_ROOT,
        executor: Executor | None = None,
        kind_workers: dict[str, int] | None = None,
        on_error: Callable[[dict], None] | None = None,
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
        # Owners whose workspace is mid-reset. Guarded by ``_singleton_lock`` so
        # the reset barrier's check-and-reserve and ``submit``'s admission
        # decision are one atomic step, closing the reset/submit race.
        self._reset_in_progress: set[str | None] = set()
        self._futures: dict[str, Future] = {}
        self._singleton_lock = threading.RLock()
        self._active_singletons: dict[str, str] = {}
        self._roots: set[Path] = {self.root}
        self._run_roots: dict[str, Path] = {}
        self._stream_notifiers: dict[str, StreamNotifier] = {}
        self.on_error = on_error

    def _emit_error(
        self, run_id: str, kind: str, error: str, user_id: str | None
    ) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(
                {
                    "runId": run_id,
                    "kind": kind,
                    "error": error,
                    "userId": user_id,
                }
            )
        except Exception:  # noqa: BLE001 - bookkeeping never masks run failure
            pass

    def register_root(self, root: Path | str) -> None:
        resolved = Path(root)
        with self._singleton_lock:
            self._roots.add(resolved)
            if resolved.is_dir():
                for path in resolved.glob("*.json"):
                    self._run_roots.setdefault(path.stem, resolved)

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
            record.update(
                state="cancelled", label="Cancelled", error=None, updated_at=_now()
            )
            self._write(run_id, record)
            self._cancel_requested.discard(run_id)
            return True
        record.update(state="cancelling", label="Cancelling", updated_at=_now())
        self._write(run_id, record)
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        return run_id in self._cancel_requested

    def create(
        self,
        kind: str,
        *,
        user_id: str | None = None,
        storage_root: Path | str | None = None,
        meta: dict[str, object] | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex
        created_at = _now()
        context = current_context()
        root = (
            Path(storage_root)
            if storage_root is not None
            else (context.paths.runs_root if context is not None else self.root)
        )
        self.register_root(root)
        with self._singleton_lock:
            self._run_roots[run_id] = root
        owner_id = (
            user_id
            if user_id is not None
            else (context.user_id if context is not None else None)
        )
        # Seed a terminal-less "pending" record so GET works before work begins.
        self._write(
            run_id,
            {
                "process": run_id,
                "kind": kind,
                "state": "pending",
                "label": "Queued",
                "current": 0,
                "total": 0,
                "created_at": created_at,
                "started_at": created_at,
                "result": None,
                "error": None,
                "error_code": None,
                "user_id": owner_id,
                "updated_at": created_at,
                "meta": meta,
            },
        )
        return run_id

    def reporter(self, run_id: str, kind: str) -> RunProgressReporter:
        record = self._read_record(run_id) or {}
        return RunProgressReporter(
            run_id,
            kind,
            self._root_for(run_id),
            created_at=str(
                record.get("created_at") or record.get("started_at") or _now()
            ),
            user_id=record.get("user_id"),
            cancel_check=lambda: self.is_cancel_requested(run_id),
            meta=record.get("meta") if isinstance(record.get("meta"), dict) else None,
            notify=self.notifier(run_id).notify,
        )

    def submit(
        self,
        kind: str,
        fn: RunFn,
        *,
        singleton_key: str | None = None,
        singleton_keys: Iterable[str] | None = None,
        user_id: str | None = None,
        max_concurrent: int | None = None,
        singleton_conflict: str = "join",
        meta: dict[str, object] | None = None,
    ) -> str:
        with self._singleton_lock:
            ctx = current_context()
            owner_id = user_id or (ctx.user_id if ctx is not None else None)
            if owner_id in self._reset_in_progress:
                raise RunResetConflict("a workspace reset is in progress")
            if max_concurrent is None and ctx is not None and owner_id == ctx.user_id:
                from resume_agent.tenancy.limits import (
                    DEFAULT_MAX_CONCURRENT_RUNS,
                    active_limit,
                )

                max_concurrent = active_limit(
                    "max_concurrent_runs", DEFAULT_MAX_CONCURRENT_RUNS
                )
            raw_singletons = list(
                dict.fromkeys(
                    [
                        key
                        for key in ([singleton_key] + list(singleton_keys or ()))
                        if key is not None
                    ]
                )
            )
            effective_singletons = tuple(
                f"{owner_id}:{key}" if owner_id is not None else key
                for key in raw_singletons
            )
            for effective_singleton in effective_singletons:
                active_id = self._active_singletons.get(effective_singleton)
                if active_id is not None:
                    snapshot = self.get(active_id)
                    if snapshot is not None and snapshot.state in ACTIVE_RUN_STATES:
                        if singleton_conflict == "raise":
                            raise RunSingletonConflict(active_id)
                        return active_id
                    self._active_singletons.pop(effective_singleton, None)

            if (
                owner_id is not None
                and max_concurrent is not None
                and max_concurrent > 0
            ):
                active_count = len(self.list_active(user_id=owner_id))
                if active_count >= max_concurrent:
                    raise RunQuotaError(
                        f"{active_count} runs already active (limit {max_concurrent})"
                    )
            run_id = self.create(kind, user_id=owner_id, meta=meta)
            reporter = self.reporter(run_id, kind)
            for effective_singleton in effective_singletons:
                self._active_singletons[effective_singleton] = run_id

            def _runner() -> None:
                # Every agent call this run makes traces to the run's own
                # directory, so a slow or expensive run can be read back
                # afterwards instead of reconstructed from logs.
                with agent_trace(self.trace_path(run_id)):
                    _execute()

            def _execute() -> None:
                try:
                    result = fn(reporter)
                    reporter.done(result=result)
                except RunCancelled:  # cooperative stop — terminal but not a failure
                    reporter.cancelled()
                except Exception as exc:  # noqa: BLE001 — surface any failure as run error
                    error = f"{type(exc).__name__}: {exc}"
                    reporter.done(
                        error=error,
                        error_code=getattr(exc, "code", None),
                        result=None,
                    )
                    self._emit_error(run_id, kind, error, reporter.user_id)
                except (
                    BaseException
                ) as exc:  # interpreter exit/interrupt: still stamp, then re-raise
                    error = f"{type(exc).__name__}: {exc}"
                    reporter.done(error=error, result=None)
                    self._emit_error(run_id, kind, error, reporter.user_id)
                    raise
                finally:
                    self._cancel_requested.discard(run_id)
                    self._release_terminal_notifier(run_id)

            submission_context = contextvars.copy_context()
            executor = self._kind_executors.get(kind, self.executor)
            try:
                future = executor.submit(submission_context.run, _runner)
            except BaseException as exc:
                for effective_singleton in effective_singletons:
                    self._active_singletons.pop(effective_singleton, None)
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
                    for effective_singleton in effective_singletons:
                        if self._active_singletons.get(effective_singleton) == run_id:
                            self._active_singletons.pop(effective_singleton, None)

            future.add_done_callback(release)
        return run_id

    @contextmanager
    def reset_guard(self, user_id: str | None) -> Iterator[None]:
        """Reserve ``user_id``'s workspace for a destructive reset.

        The active-runs check and the reservation happen under one hold of
        ``_singleton_lock``, and ``submit`` refuses reserved owners under the
        same lock, so no run can slip between the check and the truncate.
        ``list_active`` reads run files, but the lock is reentrant and reset is
        rare, so briefly holding it here does not deadlock or stall the common
        path. Raises :class:`RunResetConflict` if runs are live or a reset for
        the same owner is already underway.
        """
        with self._singleton_lock:
            if self.list_active(user_id=user_id):
                raise RunResetConflict("runs are active")
            if user_id in self._reset_in_progress:
                raise RunResetConflict("a workspace reset is in progress")
            self._reset_in_progress.add(user_id)
        try:
            yield
        finally:
            with self._singleton_lock:
                self._reset_in_progress.discard(user_id)

    def _root_for(self, run_id: str) -> Path:
        with self._singleton_lock:
            root = self._run_roots.get(run_id)
            roots = tuple(self._roots)
        if root is not None:
            return root
        for candidate in roots:
            if (candidate / f"{run_id}.json").is_file():
                with self._singleton_lock:
                    self._run_roots[run_id] = candidate
                return candidate
        return self.root

    def _read_record(self, run_id: str) -> dict | None:
        return read_progress(run_id, root=self._root_for(run_id))

    def trace_path(self, run_id: str) -> Path:
        """Return the agent-run trace path beside this run's progress record."""
        return self._root_for(run_id) / f"{run_id}.agents.ndjson"

    def stream_path(self, run_id: str) -> Path:
        """Return the event-log path beside this run's progress record."""
        return self._root_for(run_id) / f"{run_id}.stream.ndjson"

    def notifier(self, run_id: str) -> StreamNotifier:
        """Return the process-local wakeup fanout for a run stream."""
        with self._singleton_lock:
            return self._stream_notifiers.setdefault(run_id, StreamNotifier())

    def release_notifier(self, run_id: str, notifier: StreamNotifier) -> None:
        """Drop an idle terminal-run notifier without racing active sinks."""
        snapshot = self.get(run_id)
        if snapshot is None or snapshot.state not in TERMINAL_RUN_STATES:
            return
        with self._singleton_lock:
            if (
                self._stream_notifiers.get(run_id) is notifier
                and notifier.subscriber_count == 0
            ):
                self._stream_notifiers.pop(run_id, None)

    def _release_terminal_notifier(self, run_id: str) -> None:
        with self._singleton_lock:
            notifier = self._stream_notifiers.get(run_id)
            if notifier is not None and notifier.subscriber_count == 0:
                self._stream_notifiers.pop(run_id, None)

    def get(self, run_id: str) -> RunSnapshot | None:
        return parse_run_snapshot(run_id, self._read_record(run_id))

    def list_active(self, user_id: str | None = None) -> list[RunSnapshot]:
        with self._singleton_lock:
            roots = tuple(self._roots)
        snapshots = [
            snapshot
            for root in roots
            if root.exists()
            for path in root.glob("*.json")
            if (snapshot := self.get(path.stem)) is not None
            and snapshot.state in ACTIVE_RUN_STATES
            and (user_id is None or snapshot.user_id == user_id)
        ]
        return sorted(snapshots, key=lambda item: (item.created_at, item.run_id))

    def list_rehydratable(self, user_id: str | None = None) -> list[RunSnapshot]:
        """Return active runs plus failed revisions whose metadata enables retry."""
        with self._singleton_lock:
            roots = tuple(self._roots)
        snapshots = [
            snapshot
            for root in roots
            if root.exists()
            for path in root.glob("*.json")
            if (snapshot := self.get(path.stem)) is not None
            and (user_id is None or snapshot.user_id == user_id)
        ]
        visible = {
            snapshot.run_id: snapshot
            for snapshot in snapshots
            if snapshot.state in ACTIVE_RUN_STATES
        }
        latest_revision: dict[tuple[str, object], RunSnapshot] = {}
        for snapshot in snapshots:
            meta_key = (
                "versionId"
                if snapshot.kind == "revise"
                else "coverLetterId"
                if snapshot.kind == "coverLetterRevise"
                else None
            )
            artifact_id = (
                snapshot.meta.get(meta_key) if snapshot.meta and meta_key else None
            )
            if meta_key is None or artifact_id is None:
                continue
            key = (snapshot.kind, artifact_id)
            previous = latest_revision.get(key)
            # Timestamps can tie on fast retries. Prefer the active retry over
            # the failed attempt before using the random run id as a final
            # deterministic tie-breaker.
            if previous is None or (
                snapshot.created_at,
                snapshot.state in ACTIVE_RUN_STATES,
                snapshot.run_id,
            ) > (
                previous.created_at,
                previous.state in ACTIVE_RUN_STATES,
                previous.run_id,
            ):
                latest_revision[key] = snapshot
        for snapshot in latest_revision.values():
            if snapshot.state.value == "error":
                visible[snapshot.run_id] = snapshot
        return sorted(visible.values(), key=lambda item: (item.created_at, item.run_id))

    def recover_interrupted(self) -> int:
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
            self._emit_error(
                snapshot.run_id,
                snapshot.kind,
                "Backend restarted before this run completed",
                snapshot.user_id,
            )
            recovered += 1
        return recovered

    def clear(self, run_id: str) -> None:
        root = self._root_for(run_id)
        clear_progress(run_id, root=root)
        (root / f"{run_id}.stream.ndjson").unlink(missing_ok=True)
        with self._singleton_lock:
            self._run_roots.pop(run_id, None)

    def sweep(self, *, max_age_seconds: float = 86_400) -> int:
        """Delete run records whose file is older than max_age (default 1 day).

        Run files accumulate one-per-launch under RUNS_ROOT; without a sweep the
        directory grows unbounded on a long-lived server. Called on app startup.
        Returns the number of files removed.
        """
        cutoff = time.time() - max_age_seconds
        removed = 0
        with self._singleton_lock:
            roots = tuple(self._roots)
        for root in roots:
            if not root.exists():
                continue
            for path in root.glob("*.json"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                        (root / f"{path.stem}.stream.ndjson").unlink(missing_ok=True)
                        with self._singleton_lock:
                            self._run_roots.pop(path.stem, None)
                        removed += 1
                except OSError:
                    continue
        return removed

    def shutdown(self) -> None:
        # Lifespan shutdown disposes the application's database engines next.
        # Wait for owned workers first so a run cannot keep using a SQLite
        # connection after its engine has been torn down.
        for executor in self._owned_executors:
            executor.shutdown(wait=True)

    def _write(self, run_id: str, record: dict) -> None:
        atomic_write_text(
            self._root_for(run_id) / f"{run_id}.json", json.dumps(record, indent=2)
        )
        # Terminal transitions (done, error, cancelled) are written here rather
        # than through the reporter, so they need their own wakeup or a client
        # waits out the poll interval for the one event it is actually
        # waiting for.
        self.notifier(run_id).notify()


def _now() -> str:
    # Microsecond resolution so back-to-back runs (e.g. a failed revise and its
    # immediate retry) get distinct created_at/updated_at values; second
    # resolution tied them and forced the rehydration order onto the random
    # run id, which could surface a stale failed attempt over its completed retry.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
