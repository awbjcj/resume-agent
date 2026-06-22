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
