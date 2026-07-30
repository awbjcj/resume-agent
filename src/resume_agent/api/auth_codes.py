import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from resume_agent.config import Settings


CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5


class CodeVerdict(Enum):
    OK = "ok"
    INVALID = "invalid"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"


class CodeRow(Protocol):
    code_hash: str
    expires_at: datetime
    attempts: int


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str, settings: Settings) -> str:
    return hashlib.sha256(f"{code}:{settings.session_secret}".encode()).hexdigest()


def expires_at(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + CODE_TTL


def check_code(
    row: CodeRow, code: str, settings: Settings, *, now: datetime | None = None
) -> CodeVerdict:
    moment = now or datetime.now(timezone.utc)
    deadline = row.expires_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if row.attempts >= MAX_ATTEMPTS:
        return CodeVerdict.EXHAUSTED
    if deadline <= moment:
        return CodeVerdict.EXPIRED
    if hmac.compare_digest(row.code_hash, hash_code(code, settings)):
        return CodeVerdict.OK
    row.attempts += 1
    return CodeVerdict.EXHAUSTED if row.attempts >= MAX_ATTEMPTS else CodeVerdict.INVALID
