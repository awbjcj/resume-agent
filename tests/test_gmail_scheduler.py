import asyncio
from concurrent.futures import Executor, Future
from pathlib import Path
from types import SimpleNamespace

from resume_agent.api.runs.manager import RunManager
from resume_agent.db import init_db, make_engine
from resume_agent.gmail.scheduler import tick


class InlineExecutor(Executor):
    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


def _state(tmp_path: Path) -> SimpleNamespace:
    engine = make_engine("sqlite://")
    init_db(engine)
    return SimpleNamespace(
        system_engine=None,
        engine_registry=None,
        settings=None,
        template_config_dir=Path("config"),
        data_dir=tmp_path,
        run_manager=RunManager(root=tmp_path / "runs", executor=InlineExecutor()),
        engine=engine,
    )


def test_tick_skips_when_no_token(tmp_path):
    state = _state(tmp_path)
    result = asyncio.run(tick(state, work=lambda engine, reporter: {"pending": 0}))
    assert result == {}


def test_tick_runs_local_sync_when_token_exists(tmp_path):
    state = _state(tmp_path)
    (tmp_path / "gmail_token.json").write_text("{}", encoding="utf-8")
    calls = []

    def fake_work(engine, reporter, **kwargs):
        reporter.begin(1, "fake")
        calls.append(engine)
        reporter.step(1)
        return {"pending": 0, "reminders": 0}

    result = asyncio.run(tick(state, work=fake_work))
    assert "local" in result
    snapshot = state.run_manager.get(result["local"])
    assert snapshot is not None and snapshot.state.value == "done"
    assert calls == [state.engine]


def test_tick_isolates_a_failing_user(tmp_path):
    state = _state(tmp_path)
    (tmp_path / "gmail_token.json").write_text("{}", encoding="utf-8")

    def failing_work(engine, reporter, **kwargs):
        reporter.begin(1, "fake")
        raise RuntimeError("boom")

    result = asyncio.run(tick(state, work=failing_work))
    snapshot = state.run_manager.get(result["local"])
    assert snapshot is not None and snapshot.state.value == "error"
