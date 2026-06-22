"""Shared API-test isolation.

``create_app`` defaults its ``RunManager`` to the production ``RUNS_ROOT``
(``data/runs``). Any test that enters the ``TestClient`` context runs the app
lifespan, which calls ``run_manager.sweep()`` — so without this fixture a plain
``pytest`` run would unlink real run records older than 24h on the developer's
machine. Redirect every RunManager built via ``create_app`` to a per-test temp
dir unless the test already pinned ``runs_root`` itself.
"""

import pytest

from resume_agent.api import app as app_module
from resume_agent.api.runs.manager import RunManager


@pytest.fixture(autouse=True)
def _isolate_runs_root(tmp_path, monkeypatch):
    def factory(*args, **kwargs):
        kwargs.setdefault("root", tmp_path / "runs")
        return RunManager(*args, **kwargs)

    monkeypatch.setattr(app_module, "RunManager", factory)
