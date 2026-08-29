import hashlib
import logging
from functools import lru_cache
from importlib.resources import files
from typing import Protocol

import httpx

from resume_agent.api.errors import ApiException


logger = logging.getLogger(__name__)
MIN_LENGTH = 12
MAX_LENGTH = 1024


class BreachChecker(Protocol):
    def is_breached(self, password: str) -> bool: ...


class NullBreachChecker:
    def is_breached(self, password: str) -> bool:
        return False


class HibpBreachChecker:
    def is_breached(self, password: str) -> bool:
        password_bytes = password.encode()
        # HIBP's k-anonymity range protocol requires SHA-1; this is not a password
        # verifier and the request sends only the first five digest characters.
        digest = hashlib.sha1(password_bytes, usedforsecurity=False).hexdigest().upper()
        try:
            response = httpx.get(
                f"https://api.pwnedpasswords.com/range/{digest[:5]}",
                headers={"Add-Padding": "true"},
                timeout=3,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("HIBP unavailable; breach check failed open")
            return False
        return any(
            line.partition(":")[0].strip().upper() == digest[5:]
            for line in response.text.splitlines()
        )


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    content = (
        files("resume_agent.api.data").joinpath("common_passwords.txt").read_text()
    )
    seeds = {line.strip().casefold() for line in content.splitlines() if line.strip()}
    # Cover the predictable numeric variants people most often append to a
    # common base without shipping a large third-party word-list artifact.
    variants = {
        candidate
        for seed in seeds
        for number in range(100)
        for candidate in (f"{seed}{number}", f"{seed}{number:02d}")
    }
    return frozenset(seeds | variants)


def validate_password(
    password: str,
    *,
    email: str,
    display_name: str | None = None,
    checker: BreachChecker | None = None,
) -> None:
    if len(password) < MIN_LENGTH:
        raise ApiException(
            400, "PASSWORD_WEAK", "Password must be at least 12 characters"
        )
    if len(password) > MAX_LENGTH:
        raise ApiException(
            400, "PASSWORD_WEAK", "Password must be at most 1024 characters"
        )
    lowered = password.casefold()
    identity = (email.partition("@")[0], display_name or "")
    if any(
        len(part.strip()) >= 4 and part.strip().casefold() in lowered
        for part in identity
    ):
        raise ApiException(
            400, "PASSWORD_WEAK", "Password must not contain your email or name"
        )
    if lowered in _common_passwords():
        raise ApiException(400, "PASSWORD_WEAK", "That password is too common")
    if (checker or NullBreachChecker()).is_breached(password):
        raise ApiException(
            400, "PASSWORD_WEAK", "That password appeared in a known breach"
        )
