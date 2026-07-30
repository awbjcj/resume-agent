from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request


def validate_public_origin(value: str) -> str:
    base = value.strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError("APP_BASE_URL must be an absolute HTTP(S) origin")
    return base


def public_url(request: Request, path: str) -> str:
    """Build a public URL from configured application state, never host headers."""

    configured = request.app.state.settings.app_base_url
    if configured:
        base = validate_public_origin(configured)
        return f"{base}/{path.lstrip('/')}"
    return f"{str(request.base_url).rstrip('/')}/{path.lstrip('/')}"
