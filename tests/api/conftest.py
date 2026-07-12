"""Shared API-test isolation.

``create_app`` defaults its ``RunManager`` to the production ``RUNS_ROOT``
(``data/runs``). Any test that enters the ``TestClient`` context runs the app
lifespan, which calls ``run_manager.sweep()`` — so without this fixture a plain
``pytest`` run would unlink real run records older than 24h on the developer's
machine. Redirect every RunManager built via ``create_app`` to a per-test temp
dir unless the test already pinned ``runs_root`` itself.
"""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api import app as app_module
from resume_agent.api.app import create_app
from resume_agent.api.auth import hash_password
from resume_agent.api.runs.manager import RunManager


@pytest.fixture(autouse=True)
def _isolate_runs_root(tmp_path, monkeypatch):
    def factory(*args, **kwargs):
        kwargs.setdefault("root", tmp_path / "runs")
        return RunManager(*args, **kwargs)

    monkeypatch.setattr(app_module, "RunManager", factory)


@pytest.fixture
def mu_app(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('owner-password', iterations=1000)}\n"
        "SESSION_SECRET=test-session-secret\n",
        encoding="utf-8",
    )
    return create_app(
        db_url=f"sqlite:///{(tmp_path / 'data' / 'ignored.db').as_posix()}",
        env_path=env,
        data_dir=tmp_path / "data",
        runs_root=tmp_path / "legacy-runs",
        config_dir=tmp_path / "templates",
    )


@pytest.fixture
def mu_client(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        yield client
