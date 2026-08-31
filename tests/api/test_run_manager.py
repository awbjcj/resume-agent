from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock, Thread

import pytest

from resume_tailor_harness.api.runs.manager import (
    RunCancelled,
    RunManager,
    RunProgressReporter,
    RunSingletonConflict,
)
from resume_tailor_harness.api.runs.models import RunState, parse_run_snapshot
from resume_tailor_harness.progress import ProgressReporter


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


def test_error_hook_fires_once_for_a_failed_run(tmp_path):
    events = []
    mgr = RunManager(root=tmp_path, executor=InlineExecutor(), on_error=events.append)

    run_id = mgr.submit("pull", lambda _reporter: 1 / 0)

    assert events == [
        {
            "runId": run_id,
            "kind": "pull",
            "error": "ZeroDivisionError: division by zero",
            "userId": None,
        }
    ]


def test_error_hook_is_not_fired_for_success_or_cancel(tmp_path):
    events = []
    mgr = RunManager(root=tmp_path, executor=InlineExecutor(), on_error=events.append)

    mgr.submit("pull", lambda _reporter: {"ok": True})
    mgr.submit("pull", lambda _reporter: (_ for _ in ()).throw(RunCancelled))

    assert events == []


def test_error_hook_failure_never_masks_the_run_failure(tmp_path):
    def broken_hook(_payload):
        raise RuntimeError("hook failed")

    mgr = RunManager(root=tmp_path, executor=InlineExecutor(), on_error=broken_hook)
    run_id = mgr.submit("pull", lambda _reporter: 1 / 0)

    snapshot = mgr.get(run_id)
    assert snapshot is not None
    assert snapshot.state is RunState.error


def test_terminal_hook_records_every_outcome_once(tmp_path):
    events = []
    manager = RunManager(
        root=tmp_path,
        executor=InlineExecutor(),
        on_terminal=events.append,
    )

    success_id = manager.submit("discover", lambda _reporter: {"ok": True})
    failure_id = manager.submit("pull", lambda _reporter: 1 / 0)
    cancelled_id = manager.submit(
        "tailor", lambda _reporter: (_ for _ in ()).throw(RunCancelled)
    )

    assert [(event["runId"], event["status"]) for event in events] == [
        (success_id, "succeeded"),
        (failure_id, "failed"),
        (cancelled_id, "cancelled"),
    ]
    assert all(event["completedAt"].tzinfo is not None for event in events)


def test_terminal_hook_failure_never_masks_the_run_outcome(tmp_path):
    def broken_hook(_payload):
        raise RuntimeError("hook failed")

    manager = RunManager(
        root=tmp_path,
        executor=InlineExecutor(),
        on_terminal=broken_hook,
    )
    run_id = manager.submit("discover", lambda _reporter: {"ok": True})

    snapshot = manager.get(run_id)
    assert snapshot is not None
    assert snapshot.state is RunState.done


def test_reporter_checkpoint_raises_when_cancel_requested(tmp_path):
    flag = {"cancel": False}
    rep = RunProgressReporter(
        "rid", "pull", tmp_path, cancel_check=lambda: flag["cancel"]
    )
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
    rep = RunProgressReporter(
        "rid", "tailor", tmp_path, cancel_check=lambda: flag["cancel"]
    )
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
    stream_path = mgr.stream_path(run_id)
    stream_path.write_text("event\n", encoding="utf-8")
    old = time.time() - 100_000  # older than the 1-day default
    os.utime(path, (old, old))
    assert mgr.sweep() == 1
    assert not path.exists()
    assert not stream_path.exists()


def test_sweep_keeps_fresh_run_files(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("discover")
    assert mgr.sweep() == 0
    assert (tmp_path / f"{run_id}.json").exists()


def test_clear_removes_run_record_and_stream(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("profileCoachMessage")
    stream_path = mgr.stream_path(run_id)
    stream_path.write_text("event\n", encoding="utf-8")

    mgr.clear(run_id)

    assert not (tmp_path / f"{run_id}.json").exists()
    assert not stream_path.exists()


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
    assert snapshot.phase_started_at == datetime(
        2026, 6, 28, 10, 1, tzinfo=timezone.utc
    )


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
        "aaa": _run_record(
            created_at="2026-06-28T10:00:00+00:00",
            started_at="2026-06-28T11:00:00+00:00",
        ),
        "old": _run_record(created_at="2026-06-28T09:00:00+00:00", state="done"),
        "bad": _run_record(state="unknown"),
    }
    for run_id, record in records.items():
        (tmp_path / f"{run_id}.json").write_text(json.dumps(record), encoding="utf-8")

    assert [snapshot.run_id for snapshot in mgr.list_active()] == ["aaa", "bbb"]


def test_recover_interrupted_terminalizes_active_records_only(tmp_path):
    import json

    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    for run_id, state in (
        ("pending", "pending"),
        ("running", "running"),
        ("done", "done"),
    ):
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


def test_recover_interrupted_emits_user_attributed_errors(tmp_path):
    import json

    events = []
    mgr = RunManager(root=tmp_path, executor=InlineExecutor(), on_error=events.append)
    (tmp_path / "pending.json").write_text(
        json.dumps(_run_record(state="pending", user_id="user123")),
        encoding="utf-8",
    )

    assert mgr.recover_interrupted() == 1
    assert events == [
        {
            "runId": "pending",
            "kind": "pull",
            "error": "Backend restarted before this run completed",
            "userId": "user123",
        }
    ]


def test_submit_singleton_coalesces_racing_calls_and_releases_after_completion(
    tmp_path,
):
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
    next_id = mgr.submit(
        "refreshClusters", lambda _reporter: {}, singleton_key="refreshClusters"
    )
    assert next_id != first_id
    mgr.shutdown()


def test_submit_singleton_does_not_deadlock_with_inline_executor(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    first = mgr.submit(
        "refreshClusters", lambda _reporter: {}, singleton_key="clusters"
    )
    second = mgr.submit(
        "refreshClusters", lambda _reporter: {}, singleton_key="clusters"
    )

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


def test_submit_rejects_any_overlapping_exclusive_key(tmp_path):
    release = Event()
    started = Event()
    mgr = RunManager(root=tmp_path)

    def work(_reporter):
        started.set()
        release.wait(timeout=2)
        return {}

    first = mgr.submit(
        "coverLetter",
        work,
        singleton_keys=["cover-letter:1", "cover-letter:2"],
        singleton_conflict="raise",
    )
    assert started.wait(timeout=1)

    with pytest.raises(RunSingletonConflict) as error:
        mgr.submit(
            "coverLetter",
            lambda _reporter: {},
            singleton_keys=["cover-letter:2", "cover-letter:3"],
            singleton_conflict="raise",
        )

    assert error.value.run_id == first
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


def test_shutdown_waits_for_owned_workers(tmp_path):
    started = Event()
    release = Event()
    stopped = Event()
    manager = RunManager(root=tmp_path)

    def work(_reporter):
        started.set()
        assert release.wait(timeout=2)
        return {}

    manager.submit("refreshClusters", work)
    assert started.wait(timeout=1)

    shutdown_thread = Thread(
        target=lambda: (manager.shutdown(), stopped.set()), daemon=True
    )
    shutdown_thread.start()
    assert not stopped.wait(timeout=0.05)
    release.set()
    assert stopped.wait(timeout=1)
    shutdown_thread.join(timeout=1)


def _raw_record(**overrides):
    base = {
        "process": "r1",
        "kind": "tailor",
        "state": "done",
        "label": "Tailoring",
        "current": 1,
        "total": 1,
        "started_at": "2026-08-22T00:00:00+00:00",
        "created_at": "2026-08-22T00:00:00+00:00",
        "updated_at": "2026-08-22T00:00:05+00:00",
    }
    base.update(overrides)
    return base


def test_snapshot_announced_at_is_none_when_absent():
    snapshot = parse_run_snapshot("r1", _raw_record())
    assert snapshot is not None
    assert snapshot.announced_at is None


def test_snapshot_parses_announced_at():
    snapshot = parse_run_snapshot(
        "r1", _raw_record(announced_at="2026-08-22T00:01:00+00:00")
    )
    assert snapshot is not None
    assert snapshot.announced_at == datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc)


def test_snapshot_rejects_unusable_announced_at():
    for value in ("not-a-date", "2026-08-22T00:01:00", 12345, None):
        snapshot = parse_run_snapshot("r1", _raw_record(announced_at=value))
        assert snapshot is not None
        assert snapshot.announced_at is None


def test_mark_announced_stamps_a_terminal_run_once(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})

    assert mgr.mark_announced(run_id) is True
    snapshot = mgr.get(run_id)
    assert snapshot is not None and snapshot.announced_at is not None

    # Idempotent: a second ack changes nothing and reports nothing done.
    stamped = snapshot.announced_at
    assert mgr.mark_announced(run_id) is False
    updated = mgr.get(run_id)
    assert updated is not None
    assert updated.announced_at == stamped


def test_mark_announced_refuses_unknown_and_active_runs(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    assert mgr.mark_announced("does-not-exist") is False

    pending = mgr.create("tailor")
    pending_snapshot = mgr.get(pending)
    assert pending_snapshot is not None
    assert pending_snapshot.state.value == "pending"
    assert mgr.mark_announced(pending) is False
    pending_snapshot = mgr.get(pending)
    assert pending_snapshot is not None
    assert pending_snapshot.announced_at is None


def test_mark_announced_preserves_the_rest_of_the_record(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"versions": 3}, meta={"jobId": 7})

    before = mgr.get(run_id)
    assert before is not None
    mgr.mark_announced(run_id)
    after = mgr.get(run_id)
    assert after is not None

    assert after.result == before.result == {"versions": 3}
    assert after.meta == before.meta == {"jobId": 7}
    assert after.state == before.state
    assert after.kind == before.kind


def test_list_rehydratable_omits_terminal_runs_without_a_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    mgr.submit("tailor", lambda reporter: {"ok": True})
    assert mgr.list_rehydratable() == []


def test_list_rehydratable_returns_unannounced_terminal_runs_in_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})

    visible = mgr.list_rehydratable(announce_window_seconds=3600)
    assert [item.run_id for item in visible] == [run_id]

    mgr.mark_announced(run_id)
    assert mgr.list_rehydratable(announce_window_seconds=3600) == []


def test_list_rehydratable_excludes_terminal_runs_past_the_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})
    later = datetime.now(timezone.utc) + timedelta(seconds=7200)

    assert mgr.list_rehydratable(announce_window_seconds=3600, now=later) == []
    # Still individually readable -- only announcement is windowed.
    assert mgr.get(run_id) is not None


def test_list_rehydratable_still_returns_active_runs_with_a_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    pending = mgr.create("tailor")
    visible = mgr.list_rehydratable(announce_window_seconds=3600)
    assert [item.run_id for item in visible] == [pending]


def test_announce_window_never_resurrects_a_superseded_revision(tmp_path):
    """Supersession beats announcement.

    Only the latest attempt per artifact is rehydratable; a failed attempt a
    retry replaced is deliberately hidden so the retry UI is not offered a
    failure the user already moved past. The announce window must not undo that.
    """
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    meta = {"versionId": 5, "jobId": 3, "instruction": "shorter"}

    failed_id = mgr.create("revise", meta=meta)
    mgr.reporter(failed_id, "revise").done(error="first failed")
    retry_id = mgr.create("revise", meta=meta)
    mgr.reporter(retry_id, "revise").done(result={"versionId": 6})

    visible = {
        item.run_id for item in mgr.list_rehydratable(announce_window_seconds=3600)
    }
    assert visible == {retry_id}


def test_reporter_wakes_the_current_notifier_after_release(tmp_path):
    """A reconnecting client gets a fresh notifier; the worker must find it.

    ``_release_terminal_notifier`` drops the notifier once nobody is subscribed,
    and ``notifier()`` then setdefaults a NEW object for the next subscriber. A
    reporter that captured the old object's bound method would wake an orphan,
    and the reconnected stream would silently fall back to polling.
    """
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("tailor")
    reporter = mgr.reporter(run_id, "tailor")

    original = mgr.notifier(run_id)
    # Simulate the release that happens when the last subscriber goes away.
    mgr._stream_notifiers.pop(run_id, None)

    replacement = mgr.notifier(run_id)
    assert replacement is not original

    woken = Event()
    replacement.notify = lambda: woken.set()  # type: ignore[method-assign]

    reporter.begin(1, "Tailoring")

    assert woken.is_set(), "reporter woke a discarded notifier"


def test_ack_does_not_revive_a_released_notifier(tmp_path):
    """``_write`` wakes subscribers via ``notifier()``, which is a setdefault.

    Acking a terminal run therefore used to re-insert a notifier that
    ``_release_terminal_notifier`` had already popped, and nothing pops it a
    second time -- one permanent entry per acknowledged run, on a server that
    runs for weeks.
    """
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})
    assert mgr._stream_notifiers == {}

    assert mgr.mark_announced(run_id) is True

    assert mgr._stream_notifiers == {}


def test_concurrent_acks_stamp_exactly_once(tmp_path):
    """The lock makes read-check-write atomic between competing tabs."""
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})

    start = Barrier(8)
    results: list[bool] = []
    results_lock = Lock()

    def ack() -> None:
        start.wait(timeout=5)
        stamped = mgr.mark_announced(run_id)
        with results_lock:
            results.append(stamped)

    threads = [Thread(target=ack) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert results.count(True) == 1, results
    updated = mgr.get(run_id)
    assert updated is not None
    assert updated.announced_at is not None


def test_run_manager_rejects_traversal_ids_without_touching_outside_files(tmp_path):
    root = tmp_path / "runs"
    outside = tmp_path / "outside.stream.ndjson"
    outside.write_text("keep", encoding="utf-8")
    mgr = RunManager(root=root, executor=InlineExecutor())

    assert mgr.get("../outside") is None
    assert mgr.request_cancel("../outside") is False
    mgr.clear("../outside")
    assert outside.read_text(encoding="utf-8") == "keep"
    with pytest.raises(ValueError, match="invalid run id"):
        mgr.stream_path("../outside")
