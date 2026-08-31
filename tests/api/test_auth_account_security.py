import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_tailor_harness.tenancy.system_db import PasswordResetCode, User


def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"identifier": "owner", "password": "owner-password"},
    )
    assert response.status_code == 200


def _code(app):
    match = re.search(r"\b(\d{6})\b", app.state.mailer.sent[-1][2])
    assert match
    return match.group(1)


def test_legacy_email_adoption_and_revoke_all(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        _login(client)
        stale = client.cookies.get("ra_session")
        assert (
            client.post(
                "/api/account/email", json={"email": "owner@example.com"}
            ).status_code
            == 202
        )
        verified = client.post(
            "/api/account/email/verify",
            json={"email": "owner@example.com", "code": _code(mu_app)},
        )
        assert verified.status_code == 200
        assert verified.json()["needsEmail"] is False
        assert client.post("/api/account/sessions/revoke-all").status_code == 200
        assert client.get("/api/auth/me").json()["email"] == "owner@example.com"
    with TestClient(mu_app, base_url="https://testserver") as other:
        other.cookies.set("ra_session", stale)
        assert other.get("/api/auth/me").json()["username"] is None


def test_reset_and_adoption_codes_do_not_delete_each_other(mu_app):
    with TestClient(mu_app, base_url="https://testserver") as client:
        _login(client)
        with Session(mu_app.state.system_engine) as session:
            owner = (
                session.execute(select(User).where(User.username == "owner"))
                .scalars()
                .one()
            )
            owner.email = "old@example.com"
            owner.email_verified_at = datetime.now(timezone.utc)
            session.commit()
        client.post("/api/auth/password/forgot", json={"email": "old@example.com"})
        client.post("/api/account/email", json={"email": "new@example.com"})
    with Session(mu_app.state.system_engine) as session:
        rows = session.execute(select(PasswordResetCode)).scalars().all()
        assert {row.pending_email for row in rows} == {None, "new@example.com"}


def test_health_reports_mail_and_google_capabilities(mu_app):
    with TestClient(mu_app) as client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "mailConfigured": False,
            "googleOauthConfigured": False,
        }
