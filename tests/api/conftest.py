"""Shared API-test isolation.

``create_app`` defaults its ``RunManager`` to the production ``RUNS_ROOT``
(``data/runs``). Any test that enters the ``TestClient`` context runs the app
lifespan, which calls ``run_manager.sweep()`` — so without this fixture a plain
``pytest`` run would unlink real run records older than 24h on the developer's
machine. Redirect every RunManager built via ``create_app`` to a per-test temp
dir unless the test already pinned ``runs_root`` itself.

The app factory also reads the project ``.env`` when callers omit ``env_path``.
Most API tests intentionally exercise open mode, so default app instances use a
settings snapshot built without either the host environment or project dotenv.
Tests that pass ``env_path`` explicitly continue to exercise that file.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor_harness.api import app as app_module
from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.auth import hash_password
from resume_tailor_harness.api.password_policy import NullBreachChecker
from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.config import Settings
from resume_tailor_harness.mail.mailer import NullMailer


@pytest.fixture(autouse=True)
def _isolate_default_app_settings(monkeypatch):
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
    isolated_settings = Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(app_module, "get_settings", lambda: isolated_settings)


@pytest.fixture(autouse=True)
def _isolate_runs_root(tmp_path, monkeypatch):
    # ``create_app`` always passes an explicit ``root=`` (computed from
    # ``data_dir``, which itself defaults to the real repo's ``Path("data")``
    # when a test omits both ``data_dir`` and ``runs_root``), so a plain
    # ``setdefault`` can never intercept it — the key is already present.
    # Redirect only that unisolated default; a caller that pinned its own
    # ``data_dir``/``runs_root`` under ``tmp_path`` is already isolated.
    unisolated_default = Path("data") / "runs"

    def factory(*args, **kwargs):
        if kwargs.get("root") == unisolated_default:
            kwargs["root"] = tmp_path / "runs"
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
    application = create_app(
        db_url=f"sqlite:///{(tmp_path / 'data' / 'ignored.db').as_posix()}",
        app_mode="hosted",
        env_path=env,
        data_dir=tmp_path / "data",
        runs_root=tmp_path / "legacy-runs",
        config_dir=tmp_path / "templates",
    )
    application.state.mailer = NullMailer()
    application.state.breach_checker = NullBreachChecker()
    return application


@pytest.fixture
def mu_client(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        yield client
