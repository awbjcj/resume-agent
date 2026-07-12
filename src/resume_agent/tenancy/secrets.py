from __future__ import annotations

import hashlib
import secrets


def mint_secret(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
