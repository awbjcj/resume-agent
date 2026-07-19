import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.gmail import auth as gmail_auth


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as c:
        yield c


class _FakeFlow:
    """Stands in for google_auth_oauthlib Flow in both connect and callback."""

    def __init__(self):
        self.fetched_code = None

    def authorization_url(self, **kwargs):
        return (
            f"https://accounts.google.com/o/oauth2/auth?state={kwargs['state']}",
            kwargs["state"],
        )

    def fetch_token(self, code: str):
        self.fetched_code = code

    @property
    def credentials(self):
        return SimpleNamespace(
            to_json=lambda: json.dumps(
                {
                    "token": "t",
                    "refresh_token": "r",
                    "client_id": "cid",
                    "client_secret": "cs",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "scopes": gmail_auth.GMAIL_SCOPES,
                    "expiry": "2099-01-01T00:00:00Z",
                }
            )
        )


def _patch_flow(monkeypatch):
    from resume_agent.api.routers import gmail as gmail_router

    flow = _FakeFlow()
    monkeypatch.setattr(gmail_router, "_build_flow", lambda settings, redirect_uri: flow)
    return flow


def test_build_flow_disables_pkce():
    """Connect and callback build separate Flow objects, so a PKCE code_verifier
    generated at connect cannot survive to the callback's token exchange. For a
    confidential web client (client_secret) PKCE must be off, else Google rejects
    with invalid_grant 'Missing code verifier'."""
    from resume_agent.api.routers.gmail import _build_flow
    from resume_agent.config import Settings

    settings = Settings(
        google_oauth_client_id="cid", google_oauth_client_secret="cs"
    )
    flow = _build_flow(settings, "https://example.test/api/gmail/callback")

    assert flow.autogenerate_code_verifier is False
    url, _state = flow.authorization_url(state="s")
    assert "code_challenge" not in url


def test_connect_requires_client(client):
    response = client.get("/api/gmail/connect")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GMAIL_CLIENT_MISSING"


def test_connect_callback_status_disconnect_cycle(client, monkeypatch):
    _patch_flow(monkeypatch)
    app = client.app
    app.state.settings = app.state.settings.model_copy(
        update={"google_oauth_client_id": "cid", "google_oauth_client_secret": "cs"}
    )

    connected = client.get("/api/gmail/connect")
    assert connected.status_code == 200
    auth_url = connected.json()["authUrl"]
    state = auth_url.split("state=", 1)[1]

    callback = client.get(
        f"/api/gmail/callback?code=abc&state={state}", follow_redirects=False
    )
    assert callback.status_code == 307
    assert "gmail=connected" in callback.headers["location"]

    status = client.get("/api/gmail/status")
    assert status.status_code == 200
    body = status.json()
    assert body["connected"] is True
    assert body["draftCapable"] is True

    gone = client.delete("/api/gmail/token")
    assert gone.status_code == 200
    assert gone.json()["connected"] is False


def test_callback_rejects_forged_state(client, monkeypatch):
    _patch_flow(monkeypatch)
    response = client.get(
        "/api/gmail/callback?code=abc&state=forged", follow_redirects=False
    )
    assert response.status_code == 307
    assert "gmail=invalid" in response.headers["location"]


def test_callback_denied_by_user(client):
    response = client.get(
        "/api/gmail/callback?error=access_denied&state=x", follow_redirects=False
    )
    assert response.status_code == 307
    assert "gmail=denied" in response.headers["location"]
