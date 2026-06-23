from concurrent.futures import Executor, Future

import pytest

from resume_agent.api.runs.manager import RunCancelled, RunManager, RunProgressReporter
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


def test_create_run_starts_pending(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("discover")
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec["kind"] == "discover"
    assert rec["state"] in ("pending", "running", "done")


def test_submit_runs_fn_and_records_result(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def work(reporter: ProgressReporter):
        reporter.begin(1, "working")
        reporter.step(1)
        return {"statusCounts": {"shortlisted": 3}}

    run_id = mgr.submit("discover", work)
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec["state"] == "done"
    assert rec["result"] == {"statusCounts": {"shortlisted": 3}}


def test_submit_records_error(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def boom(reporter):
        raise ValueError("nope")

    run_id = mgr.submit("pull", boom)
    rec = mgr.get(run_id)
    assert rec is not None
    assert rec["state"] == "error"
    assert "nope" in rec["error"]


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
    assert rec["state"] == "cancelled"
    assert rec.get("error") is None
    # cooperative stop is not a failure and keeps partial progress
    assert rec["current"] == 1


def test_request_cancel_rejects_unknown_and_terminal_runs(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    assert mgr.request_cancel("does-not-exist") is False

    def work(reporter):
        reporter.begin(1, "x")
        reporter.step(1)
        return {}

    run_id = mgr.submit("pull", work)  # runs to done synchronously
    assert mgr.request_cancel(run_id) is False  # already terminal


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
