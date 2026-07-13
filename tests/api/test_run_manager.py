from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event, Lock

import pytest

from resume_agent.api.runs.manager import (
    RunCancelled,
    RunManager,
    RunProgressReporter,
    RunSingletonConflict,
)
from resume_agent.api.runs.models import RunState, parse_run_snapshot
from resume_agent.progress import ProgressReporter


class InlineExecutor(Executor):
    """Runs submitted callables immediately, in-thread — deterministic for tests."""

    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


class QueuedExecutor(Executor):
    """Accepts work without starting it, like a saturated thread pool."""

    def __init__(self):
        self.future: Future | None = None

    def submit(self, fn, /, *args, **kwargs):
        self.future = Future()
        return self.future


class RejectingExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        raise RuntimeError("executor unavailable")


def test_create_run_starts_pending(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("discover")
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec.kind == "discover"
    assert rec.state in (RunState.pending, RunState.running, RunState.done)


def test_submit_runs_fn_and_records_result(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def work(reporter: ProgressReporter):
        reporter.begin(1, "working")
        reporter.step(1)
        return {"statusCounts": {"shortlisted": 3}}

    run_id = mgr.submit("discover", work)
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec.state is RunState.done
    assert rec.result == {"statusCounts": {"shortlisted": 3}}


def test_submit_records_error(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def boom(reporter):
        raise ValueError("nope")

    run_id = mgr.submit("pull", boom)
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec.state is RunState.error
    assert rec.error is not None and "nope" in rec.error


def test_reporter_checkpoint_raises_when_cancel_requested(tmp_path):
    flag = {"cancel": False}
    rep = RunProgressReporter("rid", "pull", tmp_path, cancel_check=lambda: flag["cancel"])
    rep.begin(5, "working")  # not cancelled yet
    rep.step(1)
    flag["cancel"] = True
    with pytest.raises(RunCancelled):
        rep.step(2)


def test_runner_records_cancelled_state(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def work(reporter):
        reporter.begin(5, "working")
        reporter.step(1)
        raise RunCancelled  # the checkpoint firing mid-run

    run_id = mgr.submit("pull", work)
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec.state is RunState.cancelled
    assert rec.error is None
    # cooperative stop is not a failure and keeps partial progress
    assert rec.current == 1


def test_request_cancel_rejects_unknown_and_terminal_runs(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    assert mgr.request_cancel("does-not-exist") is False

    def work(reporter):
        reporter.begin(1, "x")
        reporter.step(1)
        return {}

    run_id = mgr.submit("pull", work)  # runs to done synchronously
    assert mgr.request_cancel(run_id) is False  # already terminal


def test_request_cancel_immediately_cancels_queued_run(tmp_path):
    executor = QueuedExecutor()
    mgr = RunManager(root=tmp_path, executor=executor)
    run_id = mgr.submit("tailor", lambda reporter: {"jobs": []})

    assert mgr.request_cancel(run_id) is True
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec.state is RunState.cancelled
    assert executor.future is not None and executor.future.cancelled()


def test_request_cancel_marks_running_run_as_cancelling(tmp_path):
    executor = QueuedExecutor()
    mgr = RunManager(root=tmp_path, executor=executor)
    run_id = mgr.submit("tailor", lambda reporter: {"jobs": []})
    assert executor.future is not None
    assert executor.future.set_running_or_notify_cancel() is True

    assert mgr.request_cancel(run_id) is True
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec.state is RunState.cancelling
    assert rec.label == "Cancelling"


def test_reporter_done_honours_a_late_cancel_request(tmp_path):
    flag = {"cancel": False}
    rep = RunProgressReporter("rid", "tailor", tmp_path, cancel_check=lambda: flag["cancel"])
    rep.begin(1, "Tailoring")
    flag["cancel"] = True

    with pytest.raises(RunCancelled):
        rep.done(result={"jobs": []})


def test_submit_stamps_terminal_on_base_exception(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def interrupt(reporter):
        raise KeyboardInterrupt("stop")

    # BaseException propagates (re-raised) but a terminal record is still written.
    with pytest.raises(KeyboardInterrupt):
        mgr.submit("pull", interrupt)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    import json
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["state"] == "error"
    assert "KeyboardInterrupt" in rec["error"]


def test_sweep_removes_stale_run_files(tmp_path):
    import os
    import time

    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("discover")
    path = tmp_path / f"{run_id}.json"
    old = time.time() - 100_000  # older than the 1-day default
    os.utime(path, (old, old))
    assert mgr.sweep() == 1
    assert not path.exists()


def test_sweep_keeps_fresh_run_files(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("discover")
    assert mgr.sweep() == 0
    assert (tmp_path / f"{run_id}.json").exists()


def test_suggestion_lane_is_bounded_without_blocking_default_runs(tmp_path):
    release = Event()
    first_started = Event()
    second_started = Event()
    default_finished = Event()
    live = 0
    maximum = 0
    lock = Lock()

    def suggestion_work(started):
        def work(_reporter):
            nonlocal live, maximum
            with lock:
                live += 1
                maximum = max(maximum, live)
            started.set()
            release.wait(timeout=2)
            with lock:
                live -= 1
            return {}

        return work

    mgr = RunManager(root=tmp_path, kind_workers={"suggestion": 1})
    try:
        mgr.submit("suggestion", suggestion_work(first_started))
        assert first_started.wait(timeout=1)
        mgr.submit("suggestion", suggestion_work(second_started))
        mgr.submit("pull", lambda _reporter: default_finished.set() or {})

        assert default_finished.wait(timeout=1)
        assert not second_started.is_set()
        assert maximum == 1
    finally:
        release.set()
        mgr.shutdown()


def _run_record(**overrides):
    record = {
        "process": "stored-id",
        "kind": "pull",
        "state": "running",
        "label": "Pulling",
        "current": 1,
        "total": 5,
        "created_at": "2026-06-28T10:00:00+00:00",
        "started_at": "2026-06-28T10:01:00+00:00",
        "updated_at": "2026-06-28T10:01:01+00:00",
        "result": None,
        "error": None,
    }
    record.update(overrides)
    return record


def test_parse_run_snapshot_uses_requested_id_and_typed_state():
    snapshot = parse_run_snapshot("file-id", _run_record())

    assert snapshot is not None
    assert snapshot.run_id == "file-id"
    assert snapshot.state is RunState.running
    assert snapshot.created_at == datetime(2026, 6, 28, 10, tzinfo=timezone.utc)
    assert snapshot.phase_started_at == datetime(2026, 6, 28, 10, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "mystery"),
        ("kind", ""),
        ("current", -1),
        ("current", True),
        ("total", -1),
        ("started_at", "not-a-date"),
        ("updated_at", "2026-06-28T10:01:01"),
    ],
)
def test_parse_run_snapshot_rejects_invalid_file_data(field, value):
    assert parse_run_snapshot("file-id", _run_record(**{field: value})) is None


def test_list_active_filters_invalid_and_sorts_by_creation_time_then_id(tmp_path):
    import json

    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    records = {
        "bbb": _run_record(created_at="2026-06-28T10:00:00+00:00"),
        "aaa": _run_record(created_at="2026-06-28T10:00:00+00:00", started_at="2026-06-28T11:00:00+00:00"),
        "old": _run_record(created_at="2026-06-28T09:00:00+00:00", state="done"),
        "bad": _run_record(state="unknown"),
    }
    for run_id, record in records.items():
        (tmp_path / f"{run_id}.json").write_text(json.dumps(record), encoding="utf-8")

    assert [snapshot.run_id for snapshot in mgr.list_active()] == ["aaa", "bbb"]


def test_recover_interrupted_terminalizes_active_records_only(tmp_path):
    import json

    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    for run_id, state in (("pending", "pending"), ("running", "running"), ("done", "done")):
        (tmp_path / f"{run_id}.json").write_text(
            json.dumps(_run_record(state=state)), encoding="utf-8"
        )

    assert mgr.recover_interrupted() == 2
    pending = mgr.get("pending")
    running = mgr.get("running")
    done = mgr.get("done")
    assert pending is not None
    assert running is not None
    assert done is not None
    assert pending.state is RunState.error
    assert running.state is RunState.error
    assert done.state is RunState.done
    assert mgr.list_active() == []


def test_submit_singleton_coalesces_racing_calls_and_releases_after_completion(tmp_path):
    barrier = Barrier(3)
    release = Event()
    started = Event()
    calls = 0
    calls_lock = Lock()
    mgr = RunManager(root=tmp_path)

    def work(_reporter):
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(timeout=2)
        return {}

    def submit():
        barrier.wait()
        return mgr.submit("refreshClusters", work, singleton_key="refreshClusters")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit)
        second = pool.submit(submit)
        barrier.wait()
        assert started.wait(timeout=1)
        first_id = first.result(timeout=1)
        second_id = second.result(timeout=1)
        assert first_id == second_id
        assert calls == 1
        release.set()

    for future in list(mgr._futures.values()):
        future.result(timeout=2)
    next_id = mgr.submit("refreshClusters", lambda _reporter: {}, singleton_key="refreshClusters")
    assert next_id != first_id
    mgr.shutdown()


def test_submit_singleton_does_not_deadlock_with_inline_executor(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    first = mgr.submit("refreshClusters", lambda _reporter: {}, singleton_key="clusters")
    second = mgr.submit("refreshClusters", lambda _reporter: {}, singleton_key="clusters")

    assert first != second


def test_submit_can_raise_for_an_active_singleton_and_persists_meta(tmp_path):
    release = Event()
    started = Event()
    mgr = RunManager(root=tmp_path)

    def work(_reporter):
        started.set()
        release.wait(timeout=2)
        return {}

    first = mgr.submit(
        "revise",
        work,
        singleton_key="revise:5",
        singleton_conflict="raise",
        meta={"versionId": 5, "instruction": "tighter"},
    )
    assert started.wait(timeout=1)
    with pytest.raises(RunSingletonConflict) as error:
        mgr.submit(
            "revise",
            lambda _reporter: {},
            singleton_key="revise:5",
            singleton_conflict="raise",
        )
    assert error.value.run_id == first
    assert mgr.get(first).meta == {"versionId": 5, "instruction": "tighter"}  # type: ignore[union-attr]
    release.set()
    mgr.shutdown()


def test_submit_failure_leaves_a_terminal_record_not_a_ghost_active_run(tmp_path):
    mgr = RunManager(root=tmp_path, executor=RejectingExecutor())

    with pytest.raises(RuntimeError, match="executor unavailable"):
        mgr.submit("pull", lambda _reporter: {}, singleton_key="pull")

    assert mgr.list_active() == []
    snapshots = [mgr.get(path.stem) for path in tmp_path.glob("*.json")]
    assert len(snapshots) == 1
    assert snapshots[0] is not None and snapshots[0].state is RunState.error
