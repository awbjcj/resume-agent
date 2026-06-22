from concurrent.futures import Executor, Future

from resume_agent.api.runs.manager import RunManager
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
    assert rec["state"] == "done"
    assert rec["result"] == {"statusCounts": {"shortlisted": 3}}


def test_submit_records_error(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def boom(reporter):
        raise ValueError("nope")

    run_id = mgr.submit("pull", boom)
    rec = mgr.get(run_id)
    assert rec["state"] == "error"
    assert "nope" in rec["error"]


def test_submit_stamps_terminal_on_base_exception(tmp_path):
    import pytest

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
