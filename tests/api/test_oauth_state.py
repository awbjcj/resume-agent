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
    assert auth.verify_oauth_state("garbage", SETTINGS) is None
    assert (
        auth.verify_oauth_state(
            state, Settings.model_validate({"session_secret": "different"}), now=1.0
        )
        is None
    )
