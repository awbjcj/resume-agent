from typing import cast

import pytest

from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.runs.launch import launch, session_work
from resume_tailor_harness.api.runs.manager import (
    RunManager,
    RunQuotaError,
    RunResetConflict,
    RunSingletonConflict,
)
from resume_tailor_harness.progress import ProgressReporter


class _RecordStub:
    """Every attribute record_to_run reads off a RunSnapshot (api/runs/sse.py:13)."""

    kind = "pull"
    state = "running"
    label = ""
    percent = 0
    current = 0
    total = 0
    eta_text = None
    result = None
    error = None
    error_code = None
    meta = None
    announced_at = None

    def __init__(self, run_id: str):
        self.run_id = run_id


class _ManagerStub:
    def __init__(self, error: Exception | None = None):
        self._error = error
        self.submitted: dict | None = None

    def submit(
        self,
        kind,
        fn,
        *,
        singleton_key=None,
        singleton_keys=None,
        singleton_conflict="join",
        meta=None,
    ):
        if self._error is not None:
            raise self._error
        self.submitted = {
            "kind": kind,
            "singleton_key": singleton_key,
            "singleton_keys": singleton_keys,
            "singleton_conflict": singleton_conflict,
            "meta": meta,
        }
        return "run-1"

    def get(self, run_id):
        return _RecordStub(run_id)


def test_launch_submits_and_returns_runout():
    mgr = _ManagerStub()
    out = launch(
        cast(RunManager, mgr),
        "pull",
        lambda reporter: {},
        singleton_key="pull",
        singleton_keys=["item:1", "item:2"],
        meta={"a": 1},
    )
    assert out.run_id == "run-1"
    assert mgr.submitted == {
        "kind": "pull",
        "singleton_key": "pull",
        "singleton_keys": ["item:1", "item:2"],
        "singleton_conflict": "join",
        "meta": {"a": 1},
    }


def test_launch_maps_singleton_conflict_to_409():
    mgr = _ManagerStub(error=RunSingletonConflict("run-9"))
    with pytest.raises(ApiException) as excinfo:
        launch(
            cast(RunManager, mgr),
            "pull",
            lambda reporter: {},
            singleton_key="pull",
            singleton_conflict="raise",
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.details == {"runId": "run-9"}


def test_launch_busy_code_overrides_default():
    mgr = _ManagerStub(error=RunSingletonConflict("run-9"))
    with pytest.raises(ApiException) as excinfo:
        launch(
            cast(RunManager, mgr),
            "coach",
            lambda reporter: {},
            busy_code="COACH_BUSY",
            busy_message="A coach turn is already running",
        )
    assert excinfo.value.code == "COACH_BUSY"
    assert excinfo.value.message == "A coach turn is already running"


def test_launch_maps_quota_to_429_and_reset_to_409():
    with pytest.raises(ApiException) as excinfo:
        launch(
            cast(RunManager, _ManagerStub(error=RunQuotaError("too many"))),
            "pull",
            lambda r: {},
        )
    assert excinfo.value.status_code == 429
    with pytest.raises(ApiException) as excinfo:
        launch(
            cast(RunManager, _ManagerStub(error=RunResetConflict("reset underway"))),
            "pull",
            lambda r: {},
        )
    assert excinfo.value.status_code == 409


def test_session_work_opens_its_own_session(tmp_path):
    from resume_tailor_harness.db import init_db, make_engine

    engine = make_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    init_db(engine)
    seen = {}

    def fn(session, reporter):
        seen["session"] = session
        seen["reporter"] = reporter
        return {"ok": True}

    work = session_work(engine, fn)
    assert work(cast(ProgressReporter, "REPORTER")) == {"ok": True}
    assert seen["reporter"] == "REPORTER"
    assert seen["session"] is not None
