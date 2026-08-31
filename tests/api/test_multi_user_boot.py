from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.auth import hash_password
from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.config import Settings
from resume_tailor_harness.services.errors import list_error_records
from resume_tailor_harness.tenancy.bootstrap import BootstrapError
from resume_tailor_harness.tenancy.context import UserContext, current_context, use_context
from resume_tailor_harness.tenancy.workspace import WorkspacePaths


def _env(tmp_path, *, include_seed=True):
    path = tmp_path / ".env"
    lines = ["SESSION_SECRET=test-secret", "API_TOKEN=test-token"]
    if include_seed:
        lines.extend(
            [
                "AUTH_USERNAME=owner",
                f"AUTH_PASSWORD_HASH={hash_password('pw', iterations=1000)}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_hosted_file_backed_app_boots_multi_user(tmp_path):
    data_root = tmp_path / "data"
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        app_mode="hosted",
        data_dir=data_root,
        env_path=_env(tmp_path),
        config_dir=tmp_path / "templates",
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/health").status_code == 200
        assert (data_root / "system.db").is_file()
        assert app.state.default_context.system_engine is app.state.system_engine
        assert app.state.engine is app.state.default_context.engine


def test_hosted_file_backed_app_refuses_missing_seed_credentials(tmp_path):
    data_root = tmp_path / "data"
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        app_mode="hosted",
        data_dir=data_root,
        env_path=_env(tmp_path, include_seed=False),
    )
    with pytest.raises(BootstrapError, match="required"):
        with TestClient(app):
            pass


def test_in_memory_app_keeps_legacy_test_adapter():
    app = create_app(db_url="sqlite://", api_token="")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert app.state.system_engine is None


def test_local_file_backed_app_uses_default_user_without_auth(tmp_path):
    data_root = tmp_path / "data"
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        data_dir=data_root,
        env_path=tmp_path / "missing.env",
        config_dir=tmp_path / "templates",
    )

    with TestClient(app) as client:
        assert app.state.app_mode == "local"
        assert app.state.default_context.username == "local"
        assert client.get("/api/auth/me").json() == {
            "username": "local",
            "email": None,
            "emailVerified": False,
            "needsEmail": False,
            "googleLinked": False,
            "role": "admin",
            "authRequired": False,
        }
        assert client.get("/api/pipeline").status_code == 200


def test_local_restart_ignores_auth_and_stale_legacy_children(tmp_path):
    data_root = tmp_path / "data"
    env_path = _env(tmp_path)
    hosted = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        app_mode="hosted",
        data_dir=data_root,
        env_path=env_path,
        config_dir=tmp_path / "templates",
    )
    with TestClient(hosted, base_url="https://testserver"):
        default_user_id = hosted.state.default_context.user_id

    stale = data_root / "workday_facets"
    stale.mkdir()
    (stale / "legacy.json").write_text("{}", encoding="utf-8")
    local = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        data_dir=data_root,
        env_path=env_path,
        config_dir=tmp_path / "templates",
    )
    with TestClient(local) as client:
        assert local.state.default_context.user_id == default_user_id
        assert client.get("/api/auth/me").json()["authRequired"] is False
        assert client.get("/api/pipeline").status_code == 200


def test_run_manager_propagates_context_and_uses_workspace_root(tmp_path):
    # The executor is supplied here, so RunManager does not own it and
    # manager.shutdown() is not a barrier for it. Draining it explicitly is
    # what makes this test deterministic rather than a race the worker
    # usually wins.
    executor = ThreadPoolExecutor(max_workers=1)
    manager = RunManager(root=tmp_path / "legacy", executor=executor)
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "alice"),
        settings=Settings(
            _env_file=None,  # type: ignore[call-arg]
            anthropic_api_key="",
            openai_api_key="",
            gemini_api_key="",
            deepseek_api_key="",
        ),
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    seen = []

    def work(reporter):
        seen.append(current_context())
        return {"ok": True}

    with use_context(context):
        run_id = manager.submit("pull", work)
    executor.shutdown(wait=True)
    manager.shutdown()
    assert seen == [context]
    assert (context.paths.runs_root / f"{run_id}.json").is_file()
    assert not (tmp_path / "legacy" / f"{run_id}.json").exists()


def test_startup_recovery_records_error_in_the_owner_workspace(tmp_path):
    data_root = tmp_path / "data"
    env_path = _env(tmp_path)
    first_app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        app_mode="hosted",
        data_dir=data_root,
        env_path=env_path,
        config_dir=tmp_path / "templates",
    )
    with TestClient(first_app, base_url="https://testserver"):
        user_id = first_app.state.default_context.user_id
        runs_root = first_app.state.default_context.paths.runs_root

    writer = RunManager(root=runs_root)
    run_id = writer.create("pull", user_id=user_id, storage_root=runs_root)
    writer.shutdown()

    recovered_app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        app_mode="hosted",
        data_dir=data_root,
        env_path=env_path,
        config_dir=tmp_path / "templates",
    )
    with TestClient(recovered_app, base_url="https://testserver"):
        with Session(recovered_app.state.default_context.engine) as database:
            records = list_error_records(database)

    assert len(records) == 1
    assert records[0].run_id == run_id
    assert records[0].source_label == "pull"
