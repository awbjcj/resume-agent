"""Gmail OAuth scope reconciliation.

These drive the *real* google-auth-oauthlib / requests-oauthlib / oauthlib
stack against a canned token response, because the defect under test lives
inside that stack: oauthlib enforces RFC 6749 section 3.3 as a raw set
inequality between requested and granted scope, which cannot tell an
incremental-auth superset (harmless, and the whole point of the flow) from a
grant that is missing what we asked for. A fake Flow would exercise none of it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.routers.gmail import _build_flow, _exchange_token
from resume_agent.config import Settings
from resume_agent.gmail import auth as gmail_auth
from resume_agent.gmail.errors import GmailScopeMissing

IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
REDIRECT_URI = "https://example.test/api/gmail/callback"


def _settings() -> Settings:
    return Settings(google_oauth_client_id="cid", google_oauth_client_secret="cs")


def _stub_token_endpoint(flow, *, scope: str) -> None:
    """Answer the token POST with a Google-shaped body granting ``scope``."""
    body = json.dumps(
        {
            "access_token": "at",
            "refresh_token": "rt",
            "token_type": "Bearer",
            "expires_in": 3599,
            "scope": scope,
        }
    )
    response = SimpleNamespace(
        status_code=200,
        text=body,
        headers={"Content-Type": "application/json"},
        request=SimpleNamespace(
            url="https://oauth2.googleapis.com/token", headers={}, body=""
        ),
    )
    flow.oauth2session.request = lambda **_kwargs: response


def _stubbed_flow(scope: str):
    flow = _build_flow(_settings(), REDIRECT_URI)
    _stub_token_endpoint(flow, scope=scope)
    return flow


def test_raw_fetch_token_rejects_an_incremental_superset():
    """Pins the library behaviour the fix exists to absorb.

    ``include_granted_scopes=true`` makes Google return every scope this client
    already holds — the Google sign-in identity scopes plus the Gmail ones. The
    unmediated call raises a bare ``Warning`` from deep inside oauthlib, which
    is the production traceback being fixed.
    """
    flow = _stubbed_flow(" ".join(IDENTITY_SCOPES + gmail_auth.GMAIL_SCOPES))

    with pytest.raises(Warning, match="Scope has changed"):
        flow.fetch_token(code="abc")


def test_exchange_accepts_scopes_granted_incrementally():
    granted = IDENTITY_SCOPES + gmail_auth.GMAIL_SCOPES
    flow = _stubbed_flow(" ".join(granted))

    stored = json.loads(_exchange_token(flow, code="abc"))

    assert stored["token"] == "at"
    assert stored["refresh_token"] == "rt"
    # What is persisted is what Google granted, not what we asked for: the
    # stored list is the only scope record that survives to load_credentials.
    assert set(stored["scopes"]) == set(granted)


def test_exchange_persists_granted_scopes_when_consent_is_partial():
    """Granular consent: the user keeps readonly but unticks compose.

    That is a usable connection with drafting disabled, so it must succeed and
    report the truth — ``draft_capable`` exists precisely for this state.
    """
    flow = _stubbed_flow(" ".join([*IDENTITY_SCOPES, gmail_auth.SCOPE_READONLY]))

    stored = json.loads(_exchange_token(flow, code="abc"))

    assert gmail_auth.SCOPE_COMPOSE not in stored["scopes"]
    assert gmail_auth.SCOPE_READONLY in stored["scopes"]


def test_exchange_rejects_a_grant_without_gmail_access():
    """A token carrying only identity scopes cannot read mail.

    oauthlib's blanket check used to reject this by accident; relaxing it must
    not turn a useless grant into a green 'connected'.
    """
    flow = _stubbed_flow(" ".join(IDENTITY_SCOPES))

    with pytest.raises(GmailScopeMissing):
        _exchange_token(flow, code="abc")


def test_callback_connects_when_google_returns_a_superset(tmp_path, monkeypatch):
    """End-to-end regression for the reported failure.

    Before the fix this redirected to ``?gmail=error`` for every user who had
    signed in with Google, because the two flows share one OAuth client.
    """
    from resume_agent.api.app import create_app
    from resume_agent.api.routers import gmail as gmail_router

    granted = " ".join(IDENTITY_SCOPES + gmail_auth.GMAIL_SCOPES)
    monkeypatch.setattr(
        gmail_router,
        "_build_flow",
        lambda _settings, _redirect_uri: _stubbed_flow(granted),
    )
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as client:
        app.state.settings = app.state.settings.model_copy(
            update={"google_oauth_client_id": "cid", "google_oauth_client_secret": "cs"}
        )
        auth_url = client.get("/api/gmail/connect").json()["authUrl"]
        state = auth_url.split("state=", 1)[1].split("&", 1)[0]

        callback = client.get(
            f"/api/gmail/callback?code=abc&state={state}", follow_redirects=False
        )
        assert "gmail=connected" in callback.headers["location"]

        status = client.get("/api/gmail/status").json()
        assert status["connected"] is True
        assert status["draftCapable"] is True
