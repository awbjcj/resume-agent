import io
import tarfile
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password
from resume_agent.tenancy.system_db import UsageEvent, User
from resume_agent.tenancy.workspace import provision_workspace


def _login(client, username="owner", password="owner-password"):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _add_user(app, username="alice", role="user") -> str:
    user_id = f"{username:0<12}"[:12]
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id=user_id,
                username=username,
                password_hash=hash_password("alice-password"),
                role=role,
            )
        )
        session.commit()
    provision_workspace(
        app.state.data_dir, user_id, template_dir=app.state.template_config_dir
    )
    return user_id


def test_admin_user_management_is_role_guarded(mu_app, mu_client):
    alice_id = _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200
    assert mu_client.get("/api/admin/users").status_code == 403

    assert _login(mu_client).status_code == 200
    users = mu_client.get("/api/admin/users").json()["users"]
    assert {user["username"] for user in users} == {"owner", "alice"}
    assert (
        mu_client.patch(
            f"/api/admin/users/{alice_id}",
            json={"weeklyTokenBudget": 500, "disabled": True},
        ).status_code
        == 200
    )
    assert _login(mu_client, "alice", "alice-password").status_code == 403
    assert (
        mu_client.post(
            f"/api/admin/users/{alice_id}/reset-password",
            json={"password": "new-alice-password"},
        ).status_code
        == 200
    )


def test_admin_invites_defaults_usage_and_failure_safe_delete(mu_app, mu_client):
    alice_id = _add_user(mu_app)
    assert _login(mu_client).status_code == 200
    minted = mu_client.post("/api/admin/invites", json={"expiresInDays": 7})
    assert minted.status_code == 201
    assert minted.json()["code"].startswith("inv_")
    assert "codeHash" not in mu_client.get("/api/admin/invites").text

    defaults = mu_client.get("/api/admin/system/defaults").json()
    assert defaults["weeklyTokenBudget"] > 0
    assert (
        mu_client.put(
            "/api/admin/system/defaults",
            json={
                "weeklyTokenBudget": 5000,
                "maxActiveJobs": 50,
                "maxConcurrentRuns": 1,
            },
        ).status_code
        == 200
    )
    with Session(mu_app.state.system_engine) as session:
        session.add(
            UsageEvent(
                user_id=alice_id,
                ts=datetime.now(timezone.utc),
                weighted_total=10,
                own_key=False,
            )
        )
        session.commit()
    usage = mu_client.get("/api/admin/system/usage").json()["users"]
    assert (
        next(row for row in usage if row["username"] == "alice")["weightedTotal"] == 10
    )

    workspace = mu_app.state.data_dir / "users" / alice_id
    assert mu_client.delete(f"/api/admin/users/{alice_id}").status_code == 400
    assert (
        mu_client.delete(f"/api/admin/users/{alice_id}?confirm=DELETE").status_code
        == 200
    )
    assert not workspace.exists()


def test_delete_restores_user_and_workspace_when_cleanup_fails(
    mu_app, mu_client, monkeypatch
):
    from resume_agent.api.routers import admin_users

    alice_id = _add_user(mu_app)
    workspace = mu_app.state.data_dir / "users" / alice_id
    assert _login(mu_client).status_code == 200

    def fail_cleanup(_path):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(admin_users.shutil, "rmtree", fail_cleanup)
    response = mu_client.delete(f"/api/admin/users/{alice_id}?confirm=DELETE")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DELETE_CLEANUP_FAILED"
    assert workspace.is_dir()
    with Session(mu_app.state.system_engine) as session:
        assert session.get(User, alice_id) is not None


def test_account_password_usage_and_export(mu_app, mu_client):
    assert _login(mu_client).status_code == 200
    assert mu_client.get("/api/account/usage").json()["weightedTotal"] == 0
    exported = mu_client.get("/api/account/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/gzip"
    changed = mu_client.post(
        "/api/account/password",
        json={"currentPassword": "owner-password", "newPassword": "new-owner-password"},
    )
    assert changed.status_code == 200
    mu_client.cookies.clear()
    assert _login(mu_client, password="new-owner-password").status_code == 200


def test_account_import_requires_confirmation(mu_client):
    assert _login(mu_client).status_code == 200

    response = mu_client.post(
        "/api/account/import",
        files={"file": ("workspace.tar.gz", b"not-an-archive", "application/gzip")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_account_workspace_export_import_round_trip(mu_client):
    assert _login(mu_client).status_code == 200
    exported = mu_client.get("/api/account/export")
    assert exported.status_code == 200

    imported = mu_client.post(
        "/api/account/import?confirm=REPLACE",
        files={
            "file": (
                "workspace.tar.gz",
                exported.content,
                "application/gzip",
            )
        },
    )

    assert imported.status_code == 200
    assert imported.json() == {"status": "imported"}
    assert mu_client.get("/api/account/usage").status_code == 200


def test_account_import_rejects_invalid_archive(mu_client):
    assert _login(mu_client).status_code == 200

    response = mu_client.post(
        "/api/account/import?confirm=REPLACE",
        files={"file": ("workspace.tar.gz", b"invalid", "application/gzip")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARCHIVE"


def test_whole_root_export_is_admin_only_and_snapshots_all_databases(mu_app, mu_client):
    _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200
    assert mu_client.get("/api/admin/export").status_code == 403
    assert _login(mu_client).status_code == 200
    response = mu_client.get("/api/admin/export")
    assert response.status_code == 200
    names = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz").getnames()
    assert "system.db" in names
    assert any(name.endswith("resume_agent.db") for name in names)


def test_active_job_limit_applies_to_manual_ingest(mu_app, mu_client):
    assert _login(mu_client).status_code == 200
    owner_id = mu_app.state.default_context.user_id
    assert (
        mu_client.patch(
            f"/api/admin/users/{owner_id}", json={"maxActiveJobs": 1}
        ).status_code
        == 200
    )
    assert mu_client.post("/api/jobs", json={"jdText": "first role"}).status_code == 201
    blocked = mu_client.post("/api/jobs", json={"jdText": "second role"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "QUOTA_EXCEEDED"
