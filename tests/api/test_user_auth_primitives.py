from resume_tailor_harness.api.auth import (
    LINK_TOKEN_TTL_SECONDS,
    SESSION_LIFETIME_SECONDS,
    hash_needs_upgrade,
    hash_password,
    issue_link_token,
    issue_user_session,
    parse_session_user_id,
    verify_link_token,
    verify_password,
    verify_user_session,
)
from resume_tailor_harness.config import Settings

SETTINGS = Settings(_env_file=None, session_secret="secret")  # type: ignore[call-arg]


def test_old_password_hashes_verify_and_are_upgradeable():
    stored = hash_password("correct horse", iterations=1000)
    assert verify_password("correct horse", stored)
    assert hash_needs_upgrade(stored)
    assert not hash_needs_upgrade(hash_password("correct horse"))


def test_user_session_roundtrip_expiry_and_epoch_invalidation():
    token = issue_user_session(SETTINGS, user_id="abc123def456", epoch=0, now=1000)
    assert parse_session_user_id(token) == "abc123def456"
    assert verify_user_session(token, SETTINGS, epoch=0, now=1000) == "abc123def456"
    assert (
        verify_user_session(
            token,
            SETTINGS,
            epoch=0,
            now=1000 + SESSION_LIFETIME_SECONDS + 1,
        )
        is None
    )
    assert verify_user_session(token, SETTINGS, epoch=1, now=1000) is None


def test_link_tokens_are_signed_expiring_purpose_capabilities():
    token = issue_link_token(SETTINGS, user_id="abc123def456", purpose="sse", now=1000)
    assert verify_link_token(token, SETTINGS, purpose="sse", now=1000) == "abc123def456"
    assert verify_link_token(token, SETTINGS, purpose="download", now=1000) is None
    assert (
        verify_link_token(
            token,
            SETTINGS,
            purpose="sse",
            now=1000 + LINK_TOKEN_TTL_SECONDS + 1,
        )
        is None
    )
