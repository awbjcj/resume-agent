"""Single-account PBKDF2 password hashes and stateless HMAC sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import Request, Response

from resume_agent.config import Settings

SESSION_COOKIE = "ra_session"
OAUTH_STATE_COOKIE = "ra_google_oauth_state"
OAUTH_PKCE_COOKIE = "ra_google_oauth_pkce"
OAUTH_COOKIE_PATH = "/api/auth/google/callback"
SESSION_LIFETIME_SECONDS = 30 * 24 * 60 * 60
_PBKDF2_ITERATIONS = 600_000
LINK_TOKEN_TTL_SECONDS = 10 * 60
OAUTH_STATE_TTL_SECONDS = 10 * 60
DUMMY_PASSWORD_HASH = f"pbkdf2:{_PBKDF2_ITERATIONS}:{'00' * 16}:{'00' * 32}"


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


def hash_needs_upgrade(stored: str) -> bool:
    try:
        scheme, iterations_text, _salt, _digest = stored.split(":")
        return scheme != "pbkdf2" or int(iterations_text) < _PBKDF2_ITERATIONS
    except (AttributeError, TypeError, ValueError):
        return True


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


def _sign_user(
    settings: Settings,
    payload: str,
    password_hash: str,
    *,
    namespace: str = "session",
    epoch: int = 0,
) -> str:
    key = hmac.new(
        settings.session_secret.encode("utf-8"),
        f"{namespace}:{password_hash}:{epoch}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_user_session(
    settings: Settings,
    *,
    user_id: str,
    password_hash: str,
    epoch: int = 0,
    now: float | None = None,
) -> str:
    expiry = int((time.time() if now is None else now) + SESSION_LIFETIME_SECONDS)
    payload = f"{user_id}:{expiry}"
    return f"{payload}:{_sign_user(settings, payload, password_hash, epoch=epoch)}"


def parse_session_user_id(token: str) -> str | None:
    try:
        user_id, _expiry, _signature = token.split(":")
    except (AttributeError, ValueError):
        return None
    return user_id or None


def verify_user_session(
    token: str,
    settings: Settings,
    *,
    password_hash: str,
    epoch: int = 0,
    now: float | None = None,
) -> str | None:
    if not settings.session_secret:
        return None
    try:
        user_id, expiry_text, signature = token.split(":")
        expiry = int(expiry_text)
    except (AttributeError, TypeError, ValueError):
        return None
    payload = f"{user_id}:{expiry}"
    expected = _sign_user(settings, payload, password_hash, epoch=epoch)
    if not hmac.compare_digest(signature, expected):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return user_id


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=settings.secure_cookies or request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def issue_link_token(
    settings: Settings,
    *,
    user_id: str,
    purpose: str,
    now: float | None = None,
) -> str:
    expiry = int((time.time() if now is None else now) + LINK_TOKEN_TTL_SECONDS)
    payload = f"{user_id}:{purpose}:{expiry}"
    signature = _sign_user(settings, payload, "", namespace="link")
    return f"{payload}:{signature}"


def verify_link_token(
    token: str,
    settings: Settings,
    *,
    purpose: str,
    now: float | None = None,
) -> str | None:
    if not settings.session_secret:
        return None
    try:
        user_id, signed_purpose, expiry_text, signature = token.split(":")
        expiry = int(expiry_text)
    except (AttributeError, TypeError, ValueError):
        return None
    if signed_purpose != purpose:
        return None
    payload = f"{user_id}:{signed_purpose}:{expiry}"
    expected = _sign_user(settings, payload, "", namespace="link")
    if not hmac.compare_digest(signature, expected):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return user_id


@dataclass(frozen=True)
class OAuthState:
    mode: str
    invite_hash: str


def issue_oauth_state(
    settings: Settings,
    *,
    mode: str,
    invite_hash: str = "",
    now: float | None = None,
) -> str:
    if mode not in {"login", "register"}:
        raise ValueError("unsupported OAuth mode")
    expiry = int((time.time() if now is None else now) + OAUTH_STATE_TTL_SECONDS)
    nonce = secrets.token_urlsafe(12)
    payload = f"{mode}:{invite_hash}:{nonce}:{expiry}"
    signature = _sign_user(settings, payload, "", namespace="oauth")
    return f"{payload}:{signature}"


def verify_oauth_state(
    state: str, settings: Settings, *, now: float | None = None
) -> OAuthState | None:
    if not settings.session_secret:
        return None
    try:
        mode, invite_hash, nonce, expiry_text, signature = state.split(":")
        expiry = int(expiry_text)
    except (AttributeError, TypeError, ValueError):
        return None
    if mode not in {"login", "register"} or not nonce:
        return None
    payload = f"{mode}:{invite_hash}:{nonce}:{expiry}"
    expected = _sign_user(settings, payload, "", namespace="oauth")
    if not hmac.compare_digest(signature, expected):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return OAuthState(mode=mode, invite_hash=invite_hash)


def issue_oauth_pkce_cookie(settings: Settings, state: str, verifier: str) -> str:
    payload = f"{state}:{verifier}"
    signature = _sign_user(settings, payload, "", namespace="oauth-pkce")
    return f"{verifier}:{signature}"


def verify_oauth_pkce_cookie(
    cookie: str,
    settings: Settings,
    state: str,
) -> str | None:
    if not settings.session_secret:
        return None
    try:
        verifier, signature = cookie.rsplit(":", 1)
    except (AttributeError, ValueError):
        return None
    allowed = verifier.isascii() and all(
        character.isalnum() or character in "-._~" for character in verifier
    )
    if not allowed or not 43 <= len(verifier) <= 128:
        return None
    payload = f"{state}:{verifier}"
    expected = _sign_user(settings, payload, "", namespace="oauth-pkce")
    if not hmac.compare_digest(signature, expected):
        return None
    return verifier


def set_oauth_flow_cookies(
    request: Request,
    response: Response,
    *,
    state: str,
    verifier: str,
) -> None:
    settings = request.app.state.settings
    secure = settings.secure_cookies or request.url.scheme == "https"
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=OAUTH_COOKIE_PATH,
    )
    response.set_cookie(
        OAUTH_PKCE_COOKIE,
        issue_oauth_pkce_cookie(settings, state, verifier),
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=OAUTH_COOKIE_PATH,
    )


def oauth_flow_verifier(request: Request, state: str, settings: Settings) -> str | None:
    bound_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if not bound_state or not state or not hmac.compare_digest(bound_state, state):
        return None
    cookie = request.cookies.get(OAUTH_PKCE_COOKIE, "")
    return verify_oauth_pkce_cookie(cookie, settings, state)


def clear_oauth_flow_cookies(response: Response) -> None:
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_COOKIE_PATH)
    response.delete_cookie(OAUTH_PKCE_COOKIE, path=OAUTH_COOKIE_PATH)
