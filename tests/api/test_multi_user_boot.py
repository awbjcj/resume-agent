from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.api.auth import hash_password
from resume_agent.api.runs.manager import RunManager
from resume_agent.config import Settings
from resume_agent.services.errors import list_error_records
from resume_agent.tenancy.bootstrap import BootstrapError
from resume_agent.tenancy.context import UserContext, current_context, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


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


def test_file_backed_app_always_boots_multi_user(tmp_path):
    data_root = tmp_path / "data"
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        data_dir=data_root,
        env_path=_env(tmp_path),
        config_dir=tmp_path / "templates",
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/health").status_code == 200
        assert (data_root / "system.db").is_file()
        assert app.state.default_context.system_engine is app.state.system_engine
        assert app.state.engine is app.state.default_context.engine


def test_file_backed_app_refuses_missing_seed_credentials(tmp_path):
    data_root = tmp_path / "data"
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
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


def test_run_manager_propagates_context_and_uses_workspace_root(tmp_path):
    manager = RunManager(
        root=tmp_path / "legacy", executor=ThreadPoolExecutor(max_workers=1)
    )
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
    manager.shutdown()
    assert seen == [context]
    assert (context.paths.runs_root / f"{run_id}.json").is_file()
    assert not (tmp_path / "legacy" / f"{run_id}.json").exists()


def test_startup_recovery_records_error_in_the_owner_workspace(tmp_path):
    data_root = tmp_path / "data"
    env_path = _env(tmp_path)
    first_app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
        data_dir=data_root,
        env_path=env_path,
        config_dir=tmp_path / "templates",
    )
    with TestClient(first_app, base_url="https://testserver"):
        user_id = first_app.state.default_context.user_id
        runs_root = first_app.state.default_context.paths.runs_root

    writer = RunManager(root=runs_root)
    run_id = writer.create(
        "pull", user_id=user_id, storage_root=runs_root
    )
    writer.shutdown()

    recovered_app = create_app(
        db_url=f"sqlite:///{(data_root / 'ignored.db').as_posix()}",
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
