from resume_agent.api.auth import (
    SESSION_LIFETIME_SECONDS,
    hash_password,
    issue_session,
    session_auth_configured,
    verify_password,
    verify_session,
)
from resume_agent.config import Settings


def _settings(**updates) -> Settings:
    values = {
        "auth_username": "owner",
        "auth_password_hash": hash_password("hunter2", iterations=1_000),
        "session_secret": "test-secret",
    }
    values.update(updates)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_hash_password_roundtrip_and_random_salt():
    first = hash_password("hunter2", iterations=1_000)
    second = hash_password("hunter2", iterations=1_000)
    assert first.startswith("pbkdf2:1000:")
    assert first != second
    assert verify_password("hunter2", first)
    assert not verify_password("wrong", first)


def test_verify_password_rejects_malformed_values():
    for stored in ("", "not-a-hash", "pbkdf2:banana:00:00", "other:1:00:00"):
        assert not verify_password("x", stored)


def test_session_configuration_requires_all_fields():
    assert session_auth_configured(_settings())
    assert not session_auth_configured(_settings(auth_username=""))
    assert not session_auth_configured(_settings(auth_password_hash=""))
    assert not session_auth_configured(_settings(session_secret=""))


def test_session_roundtrip_expiry_and_tamper_rejection():
    settings = _settings()
    token = issue_session(settings, now=1_000)
    assert verify_session(token, settings, now=1_000) == "owner"
    assert (
        verify_session(token, settings, now=1_000 + SESSION_LIFETIME_SECONDS + 1)
        is None
    )
    assert verify_session(token + "0", settings, now=1_000) is None
    assert verify_session(token, _settings(session_secret="other"), now=1_000) is None
    assert verify_session("garbage", settings) is None


def test_browser_enabled_defaults_true():
    assert Settings(_env_file=None).browser_enabled is True  # type: ignore[call-arg]
