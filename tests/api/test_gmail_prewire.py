from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.routers import gmail as gmail_router
from resume_agent.tenancy.system_db import User


def test_gmail_connect_passes_login_hint_and_incremental_auth(mu_app, monkeypatch):
    captured = {}

    class FakeFlow:
        def authorization_url(self, **kwargs):
            captured.update(kwargs)
            return "https://accounts.google.com/auth", kwargs["state"]

    monkeypatch.setattr(gmail_router, "_build_flow", lambda *_args: FakeFlow())
    with TestClient(mu_app) as client:
        mu_app.state.settings = mu_app.state.settings.model_copy(
            update={
                "google_oauth_client_id": "cid",
                "google_oauth_client_secret": "secret",
            }
        )
        with Session(mu_app.state.system_engine) as session:
            user = session.execute(
                select(User).where(User.username == "owner")
            ).scalars().one()
            user.email = "owner@example.com"
            session.commit()
        assert client.post(
            "/api/auth/login",
            json={"identifier": "owner@example.com", "password": "owner-password"},
        ).status_code == 200
        assert client.get("/api/gmail/connect").status_code == 200
    assert captured["login_hint"] == "owner@example.com"
    assert captured["include_granted_scopes"] == "true"
