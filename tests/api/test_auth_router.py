import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.auth import hash_password
from resume_agent.api.deps import refresh_app_settings
from resume_agent.config import Settings


def _auth_env(tmp_path, extra: str = ""):
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('hunter2', iterations=1000)}\n"
        "SESSION_SECRET=test-secret\n"
        "BROWSER_ENABLED=false\n"
        + extra,
        encoding="utf-8",
    )
    return env


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def _no_login_delay(monkeypatch):
    from resume_agent.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "FAILED_LOGIN_DELAY_SECONDS", 0.0)


def test_login_sets_cookie_and_unlocks_guarded_api(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        assert client.get("/api/pipeline").status_code == 401
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "hunter2"},
        )
        assert response.status_code == 200
        assert response.json() == {"username": "owner", "authRequired": True}
        assert "ra_session" in response.cookies
        assert client.get("/api/pipeline").status_code == 200


def test_login_verifies_password_for_unknown_username(tmp_path, monkeypatch):
    from resume_agent.api.routers import auth as auth_router

    calls = []
    real_verify = auth_router.auth.verify_password
    monkeypatch.setattr(
        auth_router.auth,
        "verify_password",
        lambda password, stored: calls.append(password) or real_verify(password, stored),
    )
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "unknown", "password": "wrong"},
        )
    assert response.status_code == 401
    assert calls == ["wrong"]


def test_me_is_public_state_probe_and_logout_clears_cookie(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        assert client.get("/api/auth/me").json() == {
            "username": None,
            "authRequired": True,
        }
        client.post("/api/auth/login", json={"username": "owner", "password": "hunter2"})
        assert client.get("/api/auth/me").json()["username"] == "owner"
        client.post("/api/auth/logout")
        assert client.get("/api/pipeline").status_code == 401


def test_open_mode_and_bearer_compatibility(tmp_path):
    open_app = create_app(db_url="sqlite://")
    with _client(open_app) as client:
        assert client.get("/api/auth/me").json()["authRequired"] is False
        assert client.get("/api/pipeline").status_code == 200

    guarded = create_app(
        db_url="sqlite://",
        env_path=_auth_env(tmp_path, "API_TOKEN=cli-token\n"),
    )
    with _client(guarded) as client:
        assert (
            client.get(
                "/api/pipeline",
                headers={"Authorization": "Bearer cli-token"},
            ).status_code
            == 200
        )


def test_login_rejects_bad_credentials_and_unconfigured_mode(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "wrong"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"

    with _client(create_app(db_url="sqlite://")) as client:
        response = client.post(
            "/api/auth/login", json={"username": "x", "password": "y"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


def test_refresh_preserves_platform_auth_and_browser_fields(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app):
        refresh_app_settings(app, Settings(_env_file=None))
        settings = app.state.settings
        assert settings.auth_username == "owner"
        assert settings.session_secret == "test-secret"
        assert settings.browser_enabled is False
