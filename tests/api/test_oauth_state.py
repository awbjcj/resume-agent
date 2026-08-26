from resume_agent.api import auth
from resume_agent.config import Settings


SETTINGS = Settings.model_validate({"session_secret": "s3cret"})


def test_oauth_state_round_trips_and_uses_a_nonce():
    first = auth.issue_oauth_state(
        SETTINGS, mode="register", invite_hash="abc123", now=1000.0
    )
    second = auth.issue_oauth_state(
        SETTINGS, mode="register", invite_hash="abc123", now=1000.0
    )
    assert first != second
    parsed = auth.verify_oauth_state(first, SETTINGS, now=1001.0)
    assert parsed == auth.OAuthState(mode="register", invite_hash="abc123")


def test_oauth_state_rejects_tampering_expiry_and_garbage():
    state = auth.issue_oauth_state(SETTINGS, mode="login", now=0.0)
    mode, invite, nonce, expiry, signature = state.split(":")
    forged = f"register:{invite}:{nonce}:{expiry}:{signature}"
    assert auth.verify_oauth_state(forged, SETTINGS, now=1.0) is None
    assert (
        auth.verify_oauth_state(state, SETTINGS, now=auth.OAUTH_STATE_TTL_SECONDS + 1)
        is None
    )


def test_oauth_state_rejects_a_different_signing_secret():
    state = auth.issue_oauth_state(SETTINGS, mode="login", now=1000.0)
    assert auth.verify_oauth_state("garbage", SETTINGS) is None
    assert (
        auth.verify_oauth_state(
            state, Settings.model_validate({"session_secret": "different"}), now=1.0
        )
        is None
    )


def test_oauth_flow_cookie_is_random_header_safe_and_fails_closed():
    cookie = auth.issue_oauth_flow_cookie()

    assert auth._valid_oauth_flow_cookie_value(cookie) is True
    assert auth._valid_oauth_flow_cookie_value("state:raw") is False
    assert auth._valid_oauth_flow_cookie_value("unsafe\r\nSet-Cookie") is False
    assert auth._valid_oauth_flow_cookie_value("x" * 129) is False


def test_oauth_pkce_verifier_has_the_required_size_and_alphabet():
    assert auth._valid_oauth_pkce_verifier("v" * 64)
    assert auth._valid_oauth_pkce_verifier("too-short") is False
    assert auth._valid_oauth_pkce_verifier("v" * 42) is False
    assert auth._valid_oauth_pkce_verifier("v" * 129) is False
    assert auth._valid_oauth_pkce_verifier("v" * 63 + "\n") is False
