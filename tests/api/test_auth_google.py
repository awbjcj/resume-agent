from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api import auth
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, User


CLIENT = {"google_oauth_client_id": "cid", "google_oauth_client_secret": "secret"}


class _FakeFlow:
    class Credentials:
        id_token = "token"

    credentials = Credentials()

    def __init__(self):
        self.authorization_kwargs = None

    def authorization_url(self, **kwargs):
        self.authorization_kwargs = kwargs
        return "https://accounts.google.com/o/oauth2/auth?test=1", kwargs["state"]

    def fetch_token(self, code=""):
        assert code == "code"


def _configure(app):
    app.state.settings = app.state.settings.model_copy(update=CLIENT)


def _fake_google(monkeypatch, claims):
    from resume_agent.api.routers import auth_google

    flow = _FakeFlow()
    monkeypatch.setattr(auth_google, "_build_flow", lambda *_args: flow)
    monkeypatch.setattr(auth_google, "_verify_id_token", lambda *_args: claims)
    return flow


def _callback(client, app, *, mode="login", invite_hash=""):
    state = auth.issue_oauth_state(
        app.state.settings, mode=mode, invite_hash=invite_hash
    )
    return client.get(
        "/api/auth/google/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )


def test_google_start_requires_client_and_uses_identity_only_prompt(
    mu_app, monkeypatch
):
    with TestClient(mu_app) as client:
        assert client.get("/api/auth/google/start").status_code == 409
    _configure(mu_app)
    flow = _fake_google(monkeypatch, {})
    with TestClient(mu_app) as client:
        response = client.get("/api/auth/google/start")
    assert response.status_code == 200
    assert response.json()["authUrl"].startswith("https://accounts.google.com/")
    assert flow.authorization_kwargs is not None
    assert flow.authorization_kwargs["prompt"] == "select_account"


def test_google_callback_uses_configured_origin_not_forwarded_host(mu_app, monkeypatch):
    from resume_agent.api.routers import auth_google

    _configure(mu_app)
    mu_app.state.settings = mu_app.state.settings.model_copy(
        update={"app_base_url": "https://resume.example"}
    )
    flow = _FakeFlow()

    def build_flow(_settings, redirect_uri):
        assert redirect_uri == "https://resume.example/api/auth/google/callback"
        return flow

    monkeypatch.setattr(auth_google, "_build_flow", build_flow)
    with TestClient(mu_app, base_url="http://internal") as client:
        response = client.get(
            "/api/auth/google/start",
            headers={
                "x-forwarded-host": "attacker.example",
                "x-forwarded-proto": "http",
            },
        )
    assert response.status_code == 200


def test_google_start_participates_in_the_ip_budget(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {})
    with TestClient(mu_app) as client:
        for _ in range(50):
            assert client.get("/api/auth/google/start").status_code == 200
        assert client.get("/api/auth/google/start").status_code == 429


def test_google_email_link_is_strict_and_monotonic(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(
        monkeypatch,
        {"sub": "attacker-sub", "email": "owner@example.com", "email_verified": True},
    )
    with TestClient(mu_app) as client:
        with Session(mu_app.state.system_engine) as session:
            owner = (
                session.execute(select(User).where(User.username == "owner"))
                .scalars()
                .one()
            )
            owner.email = "owner@example.com"
            owner.email_verified_at = datetime.now(timezone.utc)
            owner.google_sub = "original-sub"
            owner.failed_login_count = 9
            owner.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
            session.commit()
        response = _callback(client, mu_app)
    assert response.headers["location"] == "/login?error=google_conflict"
    with Session(mu_app.state.system_engine) as session:
        owner = (
            session.execute(select(User).where(User.username == "owner"))
            .scalars()
            .one()
        )
        assert owner.google_sub == "original-sub"

    _fake_google(
        monkeypatch,
        {"sub": "original-sub", "email": "owner@example.com", "email_verified": "true"},
    )
    with TestClient(mu_app) as client:
        signed_in = _callback(client, mu_app)
        assert signed_in.headers["location"] == "/"
    with Session(mu_app.state.system_engine) as session:
        owner = (
            session.execute(select(User).where(User.username == "owner"))
            .scalars()
            .one()
        )
        assert owner.failed_login_count == 0
        assert owner.locked_until is None


def test_google_requires_exact_verified_boolean_before_email_link(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(
        monkeypatch,
        {"sub": "new-sub", "email": "owner@example.com", "email_verified": "true"},
    )
    with TestClient(mu_app) as client:
        with Session(mu_app.state.system_engine) as session:
            owner = (
                session.execute(select(User).where(User.username == "owner"))
                .scalars()
                .one()
            )
            owner.email = "owner@example.com"
            owner.email_verified_at = datetime.now(timezone.utc)
            session.commit()
        response = _callback(client, mu_app)
    assert response.headers["location"] == "/login?error=unverified_google"
    with Session(mu_app.state.system_engine) as session:
        owner = (
            session.execute(select(User).where(User.username == "owner"))
            .scalars()
            .one()
        )
        assert owner.google_sub is None


def test_google_login_without_an_account_prefills_registration(mu_app, monkeypatch):
    """A login-mode miss hands the verified Google identity to the signup form.

    It used to dead-end on /login?error=no_account, which the login page renders
    as a blank form. No account is created here: the emailed code, not Google,
    is what proves ownership of the address typed into that form.
    """
    _configure(mu_app)
    _fake_google(
        monkeypatch,
        {
            "sub": "google-stranger",
            "email": "Newcomer@Umich.edu",
            "email_verified": True,
            "name": "New Comer",
        },
    )
    with TestClient(mu_app) as client:
        response = _callback(client, mu_app)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert urlparse(response.headers["location"]).path == "/register"
    assert query["email"] == ["newcomer@umich.edu"]
    assert query["name"] == ["New Comer"]
    assert query["from"] == ["google"]
    with Session(mu_app.state.system_engine) as session:
        assert (
            session.execute(select(User).where(User.google_sub == "google-stranger"))
            .scalars()
            .first()
            is None
        )


def test_google_login_prefill_omits_a_name_google_did_not_send(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(
        monkeypatch,
        {"sub": "google-nameless", "email": "nameless@example.com"},
    )
    with TestClient(mu_app) as client:
        response = _callback(client, mu_app)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["email"] == ["nameless@example.com"]
    assert "name" not in query


def test_google_registration_consumes_invite_and_provisions_workspace(
    mu_app, monkeypatch
):
    _configure(mu_app)
    invite = "inv_google_123"
    _fake_google(
        monkeypatch,
        {"sub": "google-new", "email": "new@example.com", "email_verified": True},
    )
    with TestClient(mu_app) as client:
        with Session(mu_app.state.system_engine) as session:
            session.add(
                InviteCode(
                    id="googleinvite",
                    code_hash=hash_secret(invite),
                    created_by="u1",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
            session.commit()
        response = _callback(
            client, mu_app, mode="register", invite_hash=hash_secret(invite)
        )
        assert response.headers["location"] == "/"
        assert client.get("/api/auth/me").json()["email"] == "new@example.com"
    with Session(mu_app.state.system_engine) as session:
        invite_row = session.get(InviteCode, "googleinvite")
        assert invite_row is not None
        user = session.get(User, invite_row.used_by)
        assert user is not None
        assert user.password_hash == ""
        assert user.email_verified_at is not None
    assert (mu_app.state.data_dir / "users" / user.id).is_dir()
