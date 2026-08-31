from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy.orm import Session

from resume_tailor_harness.api.auth import hash_password
from resume_tailor_harness.api.runs.manager import RunManager, RunQuotaError, RunResetConflict
from resume_tailor_harness.config import Settings
from resume_tailor_harness.tenancy.context import UserContext, new_user_id, use_context
from resume_tailor_harness.tenancy.system_db import User
from resume_tailor_harness.tenancy.workspace import WorkspacePaths, provision_workspace


def _add_user(app, username: str, password: str) -> None:
    user = User(
        id=new_user_id(),
        username=username,
        password_hash=hash_password(password),
        role="user",
    )
    user_id = user.id
    with Session(app.state.system_engine) as session:
        session.add(user)
        session.commit()
    provision_workspace(app.state.data_dir, user_id)


def _login(client, username: str, password: str) -> None:
    response = client.post(
        "/api/auth/login", json={"identifier": username, "password": password}
    )
    assert response.status_code == 200


def test_run_quota_and_singletons_are_namespaced_by_user(tmp_path):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=4))
    release = threading.Event()

    def blocker(_reporter):
        release.wait(timeout=5)
        return {}

    first = manager.submit(
        "pull", blocker, singleton_key="pull", user_id="u1", max_concurrent=1
    )
    assert (
        manager.submit(
            "pull", blocker, singleton_key="pull", user_id="u1", max_concurrent=1
        )
        == first
    )
    other = manager.submit(
        "pull", blocker, singleton_key="pull", user_id="u2", max_concurrent=1
    )
    assert other != first
    with pytest.raises(RunQuotaError):
        manager.submit("tailor", blocker, user_id="u1", max_concurrent=1)
    assert len(manager.list_active(user_id="u1")) == 1
    release.set()
    manager.shutdown()


def test_direct_submissions_inherit_active_context_quota(tmp_path, monkeypatch):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=2))
    release = threading.Event()
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "alice"),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    monkeypatch.setattr("resume_tailor_harness.tenancy.limits.active_limit", lambda *_args: 1)

    def blocker(_reporter):
        release.wait(timeout=5)
        return {}

    with use_context(context):
        manager.submit("suggestion", blocker)
        with pytest.raises(RunQuotaError):
            manager.submit("profile-build", blocker)
    release.set()
    manager.shutdown()


def test_reset_guard_refuses_when_owner_has_active_runs(tmp_path):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=2))
    release = threading.Event()

    def blocker(_reporter):
        release.wait(timeout=5)
        return {}

    manager.submit("pull", blocker, user_id="u1")
    with pytest.raises(RunResetConflict):
        with manager.reset_guard("u1"):
            pass
    release.set()
    manager.shutdown()


def test_reset_guard_reserves_owner_and_blocks_racing_submit(tmp_path):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=2))

    # The barrier reserves the owner: a run submitted for that owner mid-reset
    # (the TOCTOU window) is refused, while other owners are unaffected.
    with manager.reset_guard("u1"):
        with pytest.raises(RunResetConflict):
            manager.submit("pull", lambda _r: {}, user_id="u1")
        assert manager.submit("pull", lambda _r: {}, user_id="u2")

    # Once the barrier exits, the owner can submit again.
    assert manager.submit("pull", lambda _r: {}, user_id="u1")
    manager.shutdown()


def test_reset_guard_is_reentrant_free_after_conflict(tmp_path):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=1))
    with manager.reset_guard("u1"):
        with pytest.raises(RunResetConflict):
            with manager.reset_guard("u1"):
                pass
    # The failed nested attempt must not have cleared the still-open outer
    # reservation prematurely; after the outer exits the owner is free.
    assert manager.submit("pull", lambda _r: {}, user_id="u1")
    manager.shutdown()


def test_foreign_run_ids_are_not_disclosed(mu_app, mu_client):
    owner_id = mu_app.state.default_context.user_id
    run_id = mu_app.state.run_manager.submit(
        "test", lambda _reporter: {}, user_id=owner_id
    )
    _add_user(mu_app, "alice", "alice-password")
    _login(mu_client, "alice", "alice-password")

    assert mu_client.get(f"/api/runs/{run_id}").status_code == 404
    token = mu_client.post("/api/auth/link-token", json={"purpose": "sse"}).json()[
        "token"
    ]
    assert mu_client.get(f"/api/runs/{run_id}/events?token={token}").status_code == 404
