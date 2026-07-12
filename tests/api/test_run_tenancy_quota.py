from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password
from resume_agent.api.runs.manager import RunManager, RunQuotaError
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import provision_workspace


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
        "/api/auth/login", json={"username": username, "password": password}
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
