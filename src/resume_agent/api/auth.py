"""Single-account PBKDF2 password hashes and stateless HMAC sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from resume_agent.config import Settings

SESSION_COOKIE = "ra_session"
SESSION_LIFETIME_SECONDS = 30 * 24 * 60 * 60
_PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2:{iterations}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations_text, salt_hex, expected_hex = stored.split(":")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            bytes.fromhex(salt_hex),
            int(iterations_text),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


def session_auth_configured(settings: Settings) -> bool:
    return bool(
        settings.auth_username
        and settings.auth_password_hash
        and settings.session_secret
    )


def _sign(settings: Settings, payload: str) -> str:
    return hmac.new(
        settings.session_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue_session(settings: Settings, *, now: float | None = None) -> str:
    issued_at = time.time() if now is None else now
    expiry = int(issued_at + SESSION_LIFETIME_SECONDS)
    payload = f"{settings.auth_username}:{expiry}"
    return f"{payload}:{_sign(settings, payload)}"


def verify_session(
    token: str, settings: Settings, *, now: float | None = None
) -> str | None:
    if not session_auth_configured(settings):
        return None
    try:
        username, expiry_text, signature = token.rsplit(":", 2)
        expiry = int(expiry_text)
    except (AttributeError, TypeError, ValueError):
        return None
    payload = f"{username}:{expiry}"
    if not hmac.compare_digest(signature, _sign(settings, payload)):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    if not hmac.compare_digest(username.encode(), settings.auth_username.encode()):
        return None
    return username
