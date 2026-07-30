import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.auth import verify_password
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, PendingRegistration, User
from resume_agent.tenancy.workspace import workspace_paths


EMAIL = "ada@example.com"
PASSWORD = "quartz-lantern-42-drift"
NEW_PASSWORD = "cobalt-meridian-77-vector"


def _invite(app, code="inv_testcode123") -> str:
    with Session(app.state.system_engine) as session:
        session.add(
            InviteCode(
                id="invite1",
                code_hash=hash_secret(code),
                created_by="owner",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        session.commit()
    return code


def _last_code(app) -> str:
    match = re.search(r"\b(\d{6})\b", app.state.mailer.sent[-1][2])
    assert match is not None
    return match.group(1)


def _register(client, invite, *, email=EMAIL):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "inviteCode": invite,
            "displayName": "Ada",
        },
    )


def test_open_registration_needs_no_invite_and_starts_byok_only(mu_app):
    mu_app.state.settings = mu_app.state.settings.model_copy(
        update={"registration_mode": "open"}
    )
    with TestClient(mu_app, base_url="https://testserver") as client:
        sent = client.post(
            "/api/auth/register",
            json={
                "email": EMAIL,
                "password": PASSWORD,
                "displayName": "Ada",
            },
        )
        assert sent.status_code == 202
        verified = client.post(
            "/api/auth/verify-email",
            json={"email": EMAIL, "code": _last_code(mu_app)},
        )
        assert verified.status_code == 200
    with Session(mu_app.state.system_engine) as session:
        user = session.execute(select(User).where(User.email == EMAIL)).scalar_one()
        assert user.shared_key_access is True
        assert user.weekly_token_budget == 250_000
        assert user.max_active_jobs == 100
        assert user.max_concurrent_runs == 1


def test_open_registration_has_a_platform_daily_capacity(mu_app):
    mu_app.state.settings = mu_app.state.settings.model_copy(
        update={"registration_mode": "open", "global_daily_signup_limit": 1}
    )
    with TestClient(mu_app, base_url="https://testserver") as client:
        first = client.post(
            "/api/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
        )
        second = client.post(
            "/api/auth/register",
            json={"email": "grace@example.com", "password": PASSWORD},
        )
    assert first.status_code == 202
    assert second.status_code == 429


def test_register_verify_login_and_reset_flow(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        invite = _invite(mu_app)
        sent = _register(client, invite)
        assert sent.status_code == 202
        assert sent.json() == {"status": "sent"}
        assert _last_code(mu_app) not in sent.text
        with Session(mu_app.state.system_engine) as session:
            assert (
                session.execute(select(User).where(User.email == EMAIL)).first() is None
            )
            assert session.execute(select(PendingRegistration)).first() is not None

        verified = client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": _last_code(mu_app)}
        )
        assert verified.status_code == 200
        assert verified.json()["emailVerified"] is True
        assert client.get("/api/auth/me").json()["email"] == EMAIL

        client.post("/api/auth/logout")
        assert (
            client.post(
                "/api/auth/login",
                json={"identifier": EMAIL.upper(), "password": PASSWORD},
            ).status_code
            == 200
        )

        forgot = client.post("/api/auth/password/forgot", json={"email": EMAIL})
        assert forgot.status_code == 202
        reset = client.post(
            "/api/auth/password/reset",
            json={
                "email": EMAIL,
                "code": _last_code(mu_app),
                "newPassword": NEW_PASSWORD,
            },
        )
        assert reset.status_code == 200
    with Session(mu_app.state.system_engine) as session:
        assert verify_password(
            NEW_PASSWORD,
            session.execute(select(User).where(User.email == EMAIL))
            .scalars()
            .one()
            .password_hash,
        )


def test_register_existing_address_is_indistinguishable(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        invite = _invite(mu_app)
        with Session(mu_app.state.system_engine) as session:
            owner = (
                session.execute(select(User).where(User.username == "owner"))
                .scalars()
                .one()
            )
            owner.email = EMAIL
            owner.email_verified_at = datetime.now(timezone.utc)
            session.commit()
        existing = _register(client, invite)
        assert existing.status_code == 202
        assert existing.content == b'{"status":"sent"}'


def test_resend_is_exactly_three_per_email_per_hour_across_ips(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        invite = _invite(mu_app)
        assert _register(client, invite).status_code == 202
        for index in range(3):
            response = client.post(
                "/api/auth/resend-code",
                json={"email": EMAIL},
                headers={"x-forwarded-for": f"10.0.0.{index}"},
            )
            assert response.status_code == 202
        blocked = client.post(
            "/api/auth/resend-code",
            json={"email": EMAIL},
            headers={"x-forwarded-for": "10.0.0.99"},
        )
        assert blocked.status_code == 429


def test_expired_invite_cannot_be_consumed(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        invite = _invite(mu_app)
        assert _register(client, invite).status_code == 202
        code = _last_code(mu_app)
        with Session(mu_app.state.system_engine) as session:
            row = session.get(InviteCode, "invite1")
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        response = client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": code}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVITE_EXPIRED"


def test_provisioning_failure_rolls_back_user_invite_and_files(mu_app, monkeypatch):
    from resume_agent.api.routers import auth_register

    created = []

    def fail_after_creating(data_root, user_id, **_kwargs):
        root = workspace_paths(data_root, user_id).root
        root.mkdir(parents=True)
        created.append(root)
        raise OSError("disk full")

    monkeypatch.setattr(auth_register, "provision_workspace", fail_after_creating)
    with TestClient(mu_app, base_url="https://testserver") as client:
        invite = _invite(mu_app)
        assert _register(client, invite).status_code == 202
        code = _last_code(mu_app)
        with pytest.raises(OSError, match="disk full"):
            client.post("/api/auth/verify-email", json={"email": EMAIL, "code": code})
    with Session(mu_app.state.system_engine) as session:
        assert session.execute(select(User).where(User.email == EMAIL)).first() is None
        invite_row = session.get(InviteCode, "invite1")
        assert invite_row is not None
        assert invite_row.used_at is None
    assert created and not created[0].exists()
