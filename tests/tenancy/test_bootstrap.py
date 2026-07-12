import pytest
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy.bootstrap import (
    BootstrapError,
    build_context,
    ensure_bootstrapped,
)
from resume_agent.tenancy.engines import EngineRegistry
from resume_agent.tenancy.system_db import User, init_system_db, make_system_engine


def _settings(**updates):
    values = {"auth_username": "owner", "auth_password_hash": "pbkdf2:1:aa:bb"}
    values.update(updates)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_bootstrap_seeds_once_and_build_context_self_heals_workspace(tmp_path):
    root = tmp_path / "data"
    engine = make_system_engine(root)
    init_system_db(engine)
    first = ensure_bootstrapped(root, engine, _settings())
    second = ensure_bootstrapped(root, engine, _settings(auth_password_hash="changed"))
    assert first.id == second.id
    assert second.password_hash == "pbkdf2:1:aa:bb"
    registry = EngineRegistry()
    context = build_context(
        first,
        root,
        _settings(),
        registry,
        system_engine=engine,
        template_dir=tmp_path,
    )
    assert context.workspace.is_dir()
    assert context.system_engine is engine
    registry.close_all()
    engine.dispose()


def test_nonempty_database_without_admin_is_rejected(tmp_path):
    root = tmp_path / "data"
    engine = make_system_engine(root)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(
            User(id="abc123def456", username="alice", password_hash="hash", role="user")
        )
        session.commit()
    with pytest.raises(BootstrapError, match="no admin"):
        ensure_bootstrapped(root, engine, _settings())
    engine.dispose()
