from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import InviteCode, User


def _login(client, username="owner", password="owner-password"):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _invite(app, *, expires_at=None):
    raw = mint_secret("inv_")
    with Session(app.state.system_engine) as session:
        session.add(
            InviteCode(
                id=mint_secret("")[:12],
                code_hash=hash_secret(raw),
                created_by=app.state.default_context.user_id,
                expires_at=expires_at
                or datetime.now(timezone.utc) + timedelta(days=14),
            )
        )
        session.commit()
    return raw


def test_login_uses_system_user_and_upgrades_weak_seed_hash(mu_app, mu_client):
    response = _login(mu_client)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert mu_client.get("/api/auth/me").json()["username"] == "owner"
    with Session(mu_app.state.system_engine) as session:
        owner = session.execute(
            select(User).where(User.username == "owner")
        ).scalar_one()
        assert not owner.password_hash.startswith("pbkdf2:1000:")
        assert owner.last_active_at is not None


def test_register_consumes_invite_and_provisions_workspace(mu_app, mu_client):
    raw = _invite(mu_app)
    response = mu_client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "long-enough-password",
            "inviteCode": raw,
        },
    )
    assert response.status_code == 201
    with Session(mu_app.state.system_engine) as session:
        alice = session.execute(
            select(User).where(User.username == "alice")
        ).scalar_one()
    assert (mu_app.state.data_dir / "users" / alice.id / "profile").is_dir()
    assert _login(mu_client, "alice", "long-enough-password").status_code == 200


def test_register_validates_inputs_and_failed_invites(mu_app, mu_client):
    invalid = mu_client.post(
        "/api/auth/register",
        json={"username": "../bad", "password": "short", "inviteCode": "bad"},
    )
    assert invalid.status_code == 422
    unknown = mu_client.post(
        "/api/auth/register",
        json={
            "username": "valid-user",
            "password": "long-enough!",
            "inviteCode": "inv_bogus",
        },
    )
    assert unknown.json()["error"]["code"] == "INVITE_INVALID"


def test_disabled_user_is_rejected_by_login_and_existing_session(mu_app, mu_client):
    assert _login(mu_client).status_code == 200
    with Session(mu_app.state.system_engine) as session:
        owner = session.execute(
            select(User).where(User.username == "owner")
        ).scalar_one()
        owner.disabled_at = datetime.now(timezone.utc)
        session.commit()
    assert mu_client.get("/api/pipeline").json()["error"]["code"] == "USER_DISABLED"
    mu_client.cookies.clear()
    assert _login(mu_client).json()["error"]["code"] == "USER_DISABLED"
