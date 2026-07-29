# Email-Verified Accounts, Google Sign-In, and Auth Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make email the verified account identity, add Google sign-in that pre-wires Gmail sync, replace admin-only password recovery with emailed single-use codes, and harden the password and rate-limiting surface.

**Architecture:** A new `mail/` package provides the only outbound-mail seam, with `send()` raising and `notify()` swallowing. `system.db` gains auth columns plus three tables via an additive `PRAGMA table_info` migration. Registration writes a `PendingRegistration` and only creates the `User` once the emailed code is verified, so a typo cannot burn a one-time invite. Sessions stay stateless — `session_epoch` joins the HMAC key material, making revocation a single integer bump.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (`SystemBase` declarative), Pydantic v2 (`CamelModel`), stdlib `smtplib`, `httpx`, pytest. Web: React 19, react-router-dom, TanStack Query, Base UI + shadcn, Tailwind v4, Vitest + Testing Library + MSW.

**Spec:** `docs/superpowers/specs/2026-07-28-auth-email-verification-oauth-design.md`

## Global Constraints

- **Tests run fully offline.** No SMTP, no HIBP, no Google. Backend: `.venv/Scripts/python.exe -m pytest`. Web: `cd web && npm run test:run`.
- **Lint:** `ruff check` must pass. Web: `cd web && npm run lint`.
- **Codes are six digits**, generated with `secrets.randbelow(1_000_000)` zero-padded to 6, stored only as `sha256(f"{code}:{session_secret}")`, TTL **15 minutes**, destroyed after **5 failed attempts**.
- **A verification or reset code must never appear in any API response body.** Every code-issuing endpoint gets a test asserting this.
- **`password_hash` stays `NOT NULL`**; the empty string `""` is the "no password" sentinel (SQLite cannot relax `NOT NULL` via `ALTER TABLE`).
- **Enumeration:** `register` and `password/forgot` return byte-identical status and body for known and unknown addresses.
- **Platform SMTP settings are process-environment only** — never part of the per-workspace `secrets.env` overlay.
- **`gmail.send` remains permanently out of scope.** Platform mail is a separate actor and never touches a user's Gmail token or the Google OAuth client.
- New system tables subclass `SystemBase` from `resume_agent.tenancy.system_db` and use `String(12)` hex ids via `uuid.uuid4().hex[:12]`.
- Pydantic request/response schemas subclass `CamelModel` (`api/schemas/base.py`) — snake_case in Python, camelCase on the wire.
- Errors raise `ApiException(status, CODE, message)` from `api/errors.py`.

## File Structure

**New — backend**

| Path                                             | Responsibility                                                                     |
| ------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `src/resume_agent/mail/__init__.py`              | Package marker                                                                     |
| `src/resume_agent/mail/mailer.py`                | `Mailer` protocol, `SmtpMailer`, `NullMailer`, `MailDeliveryError`, `build_mailer` |
| `src/resume_agent/mail/messages.py`              | Plain-text message bodies                                                          |
| `src/resume_agent/tenancy/migrate_system.py`     | Additive `system.db` column/index migration                                        |
| `src/resume_agent/api/password_policy.py`        | `validate_password`, `BreachChecker`, `HibpBreachChecker`, `NullBreachChecker`     |
| `src/resume_agent/api/data/common_passwords.txt` | Offline common-password floor                                                      |
| `src/resume_agent/api/attempts.py`               | Durable rate-limit budgets + account lockout tiers                                 |
| `src/resume_agent/api/auth_codes.py`             | Code generation, hashing, and attempt-counting verification                        |
| `src/resume_agent/api/routers/auth_register.py`  | `register`, `verify-email`, `resend-code`                                          |
| `src/resume_agent/api/routers/auth_password.py`  | `password/forgot`, `password/reset`                                                |
| `src/resume_agent/api/routers/auth_google.py`    | `google/start`, `google/callback`                                                  |
| `src/resume_agent/api/schemas/auth_email.py`     | Schemas for the above routers                                                      |

**Modified — backend**

| Path                              | Change                                                                                     |
| --------------------------------- | ------------------------------------------------------------------------------------------ |
| `config.py`                       | SMTP + `app_base_url` + `auth_email` settings                                              |
| `tenancy/system_db.py`            | `users` columns; `PendingRegistration`, `PasswordResetCode`, `LoginAttempt`                |
| `tenancy/bootstrap.py`            | Seed admin email from `AUTH_EMAIL`                                                         |
| `api/auth.py`                     | `session_epoch` in HMAC key; `set_session_cookie`; OAuth state signing                     |
| `api/deps.py:_authenticated_user` | Pass `epoch=` to `verify_user_session`                                                     |
| `api/app.py`                      | `app.state.mailer`, `app.state.breach_checker`, run `migrate_system_db`, mount new routers |
| `api/routers/auth.py`             | Login by email + legacy username fallback; lockout; `MeResponse` fields                    |
| `api/routers/account.py`          | Email set/verify, `sessions/revoke-all`, `DELETE /google`, policy on change-password       |
| `api/routers/gmail.py`            | `login_hint` + `include_granted_scopes`                                                    |
| `api/routers/health.py`           | `HealthOut` with `mailConfigured`                                                          |
| `api/schemas/auth.py`             | `email` replaces `username`; `MeResponse` fields                                           |
| `api/schemas/account.py`          | Email/verify request schemas                                                               |

**New — web** (all under `web/src/features/auth/` unless noted)

`AuthLayout.tsx`, `OtpInput.tsx`, `strength.ts`, `PasswordStrengthMeter.tsx`, `GoogleButton.tsx`, `VerifyEmailPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`, `CompleteProfilePage.tsx`, plus `web/src/features/account/SecurityCard.tsx`.

**Modified — web:** `LoginPage.tsx`, `RegisterPage.tsx`, `AuthGate.tsx`, `app/router.tsx`, `features/account/AccountPage.tsx`.

---

## Phase 1 — Substrate (no behavior change)

### Task 1: Mail seam

**Files:**

- Create: `src/resume_agent/mail/__init__.py`, `src/resume_agent/mail/mailer.py`, `src/resume_agent/mail/messages.py`
- Modify: `src/resume_agent/config.py` (after the Gmail block, around line 62)
- Test: `tests/test_mailer.py`

**Interfaces:**

- Consumes: `resume_agent.config.Settings`
- Produces:
  - `Mailer` protocol with `send(*, to: str, subject: str, body: str) -> None` and `notify(...) -> None`
  - `MailDeliveryError(RuntimeError)`
  - `NullMailer()` with a `.sent: list[tuple[str, str, str]]` capture list
  - `SmtpMailer(settings: Settings)`
  - `build_mailer(settings: Settings) -> Mailer`
  - `mail_configured(settings: Settings) -> bool`
  - `messages.Message(subject: str, body: str)` frozen dataclass
  - `messages.verification_code(code: str) -> Message`
  - `messages.reset_code(code: str) -> Message`
  - `messages.password_changed(base_url: str) -> Message`
  - `messages.google_linked(base_url: str) -> Message`
  - `messages.signup_on_existing(base_url: str) -> Message`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mailer.py`:

```python
import logging

import pytest

from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.mail.mailer import (
    MailDeliveryError,
    NullMailer,
    SmtpMailer,
    build_mailer,
    mail_configured,
)


def test_build_mailer_returns_null_when_smtp_host_unset():
    settings = Settings(_env_file=None)
    assert isinstance(build_mailer(settings), NullMailer)
    assert mail_configured(settings) is False


def test_build_mailer_returns_smtp_when_host_set():
    settings = Settings(_env_file=None, smtp_host="smtp.example.com")
    assert isinstance(build_mailer(settings), SmtpMailer)
    assert mail_configured(settings) is True


def test_null_mailer_captures_and_warns(caplog):
    mailer = NullMailer()
    with caplog.at_level(logging.WARNING):
        mailer.send(to="a@example.com", subject="Code", body="123456")
    assert mailer.sent == [("a@example.com", "Code", "123456")]
    assert "MAIL NOT CONFIGURED" in caplog.text


def test_smtp_send_raises_mail_delivery_error_on_transport_failure(monkeypatch):
    settings = Settings(_env_file=None, smtp_host="smtp.example.com")

    def explode(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("smtplib.SMTP", explode)
    with pytest.raises(MailDeliveryError):
        SmtpMailer(settings).send(to="a@example.com", subject="s", body="b")


def test_smtp_notify_swallows_delivery_failure(monkeypatch, caplog):
    settings = Settings(_env_file=None, smtp_host="smtp.example.com")
    monkeypatch.setattr(
        "smtplib.SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    )
    with caplog.at_level(logging.ERROR):
        SmtpMailer(settings).notify(to="a@example.com", subject="s", body="b")
    assert "notification" in caplog.text


def test_messages_carry_the_code_and_ttl():
    message = messages.verification_code("123456")
    assert "123456" in message.body
    assert "15 minutes" in message.body


def test_notice_omits_links_when_base_url_blank():
    assert "http" not in messages.password_changed("").body
    assert "https://app.test/login" in messages.password_changed("https://app.test").body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mailer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.mail'`

- [ ] **Step 3: Add the Settings fields**

In `src/resume_agent/config.py`, immediately after the `gmail_max_messages` line (the end of the Gmail block, ~line 62), add:

```python
    # Platform outbound mail (verification codes, password reset, security
    # notices). Process-environment only — deliberately NOT part of the
    # per-workspace secrets.env overlay, so a tenant cannot redirect
    # platform mail. This is not the user's Gmail; see CLAUDE.md.
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # falls back to smtp_username when blank
    smtp_starttls: bool = True
    app_base_url: str = ""  # absolute base for links in notice emails
    auth_email: str = ""  # bootstrap admin's verified address
```

- [ ] **Step 4: Write `mail/__init__.py` and `mail/messages.py`**

`src/resume_agent/mail/__init__.py`:

```python
"""Platform outbound mail. Not the user's Gmail — see CLAUDE.md."""
```

`src/resume_agent/mail/messages.py`:

```python
"""Plain-text bodies for platform mail. No HTML, no tracking, no attachments."""

from __future__ import annotations

from dataclasses import dataclass

CODE_TTL_MINUTES = 15


@dataclass(frozen=True)
class Message:
    subject: str
    body: str


def _link_line(base_url: str, path: str, label: str) -> str:
    return f"\n{label}: {base_url.rstrip('/')}{path}\n" if base_url else ""


def verification_code(code: str) -> Message:
    return Message(
        subject="Your Resume Agent verification code",
        body=(
            f"Your verification code is {code}\n\n"
            f"It expires in {CODE_TTL_MINUTES} minutes and can be used once.\n"
            "If you did not request this, you can ignore this message.\n"
        ),
    )


def reset_code(code: str) -> Message:
    return Message(
        subject="Your Resume Agent password reset code",
        body=(
            f"Your password reset code is {code}\n\n"
            f"It expires in {CODE_TTL_MINUTES} minutes and can be used once.\n"
            "If you did not request a reset, your password is unchanged and no\n"
            "action is needed.\n"
        ),
    )


def password_changed(base_url: str) -> Message:
    return Message(
        subject="Your Resume Agent password was changed",
        body=(
            "The password on your Resume Agent account was just changed, and\n"
            "every signed-in device was signed out.\n\n"
            "If this was not you, reset your password immediately."
            + _link_line(base_url, "/forgot-password", "Reset your password")
        ),
    )


def google_linked(base_url: str) -> Message:
    return Message(
        subject="A Google account was linked to your Resume Agent account",
        body=(
            "A Google account can now be used to sign in to your Resume Agent\n"
            "account.\n\nIf this was not you, reset your password immediately."
            + _link_line(base_url, "/forgot-password", "Reset your password")
        ),
    )


def signup_on_existing(base_url: str) -> Message:
    return Message(
        subject="Someone tried to sign up with your email",
        body=(
            "Someone attempted to create a Resume Agent account with this email\n"
            "address, but an account already exists. No new account was created\n"
            "and nothing changed.\n\n"
            "If that was you, sign in instead — or reset your password if you\n"
            "have forgotten it."
            + _link_line(base_url, "/login", "Sign in")
            + _link_line(base_url, "/forgot-password", "Reset your password")
        ),
    )
```

- [ ] **Step 5: Write `mail/mailer.py`**

```python
"""The only outbound-mail seam.

``send`` raises and ``notify`` swallows, and that distinction is
load-bearing: a verification code that cannot be delivered must fail the
request loudly, while a security notice must never fail an operation whose
state change already committed.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from resume_agent.config import Settings

logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 10.0
_IMPLICIT_TLS_PORT = 465


class MailDeliveryError(RuntimeError):
    """A message could not be handed to the MTA."""


class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...
    def notify(self, *, to: str, subject: str, body: str) -> None: ...


class NullMailer:
    """Logs instead of sending; used when SMTP_HOST is unset.

    ``send`` deliberately succeeds so local development and the offline test
    suite can complete registration with no credentials. The risk of a
    misconfigured production box logging live codes is covered by
    ``mailConfigured`` on /api/health and the admin banner.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))
        logger.warning(
            "MAIL NOT CONFIGURED — would send to %s: %s\n%s", to, subject, body
        )

    def notify(self, *, to: str, subject: str, body: str) -> None:
        self.send(to=to, subject=subject, body=body)


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _message(self, to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._settings.smtp_from or self._settings.smtp_username
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return message

    def send(self, *, to: str, subject: str, body: str) -> None:
        settings = self._settings
        implicit_tls = settings.smtp_port == _IMPLICIT_TLS_PORT
        opener = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
        try:
            with opener(
                settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT_SECONDS
            ) as client:
                if settings.smtp_starttls and not implicit_tls:
                    client.starttls()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(self._message(to, subject, body))
        except (smtplib.SMTPException, OSError) as error:
            raise MailDeliveryError(str(error)) from error

    def notify(self, *, to: str, subject: str, body: str) -> None:
        try:
            self.send(to=to, subject=subject, body=body)
        except MailDeliveryError:
            logger.exception("security notification to %s failed", to)


def mail_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host)


def build_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(settings) if mail_configured(settings) else NullMailer()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mailer.py -v && ruff check src/resume_agent/mail src/resume_agent/config.py`
Expected: 7 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/mail src/resume_agent/config.py tests/test_mailer.py
git commit -m "Adds the platform outbound-mail seam with raising send and swallowing notify"
```

---

### Task 2: System DB schema and migration

**Files:**

- Modify: `src/resume_agent/tenancy/system_db.py`
- Create: `src/resume_agent/tenancy/migrate_system.py`
- Test: `tests/tenancy/test_migrate_system.py`

**Interfaces:**

- Consumes: `SystemBase`, `utc_now` from `tenancy/system_db.py`
- Produces:
  - `User` gains `email: Mapped[str | None]`, `email_verified_at: Mapped[datetime | None]`, `google_sub: Mapped[str | None]`, `session_epoch: Mapped[int]`, `failed_login_count: Mapped[int]`, `locked_until: Mapped[datetime | None]`
  - `PendingRegistration`, `PasswordResetCode`, `LoginAttempt` models
  - `migrate_system_db(engine: Engine) -> None`
  - `has_password(user: User) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/tenancy/test_migrate_system.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from resume_agent.tenancy.migrate_system import migrate_system_db
from resume_agent.tenancy.system_db import (
    LoginAttempt,
    PasswordResetCode,
    PendingRegistration,
    User,
    has_password,
    init_system_db,
)

_LEGACY_USERS_DDL = """
CREATE TABLE users (
    id VARCHAR(12) NOT NULL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR NOT NULL,
    role VARCHAR(8) NOT NULL,
    disabled_at DATETIME,
    last_active_at DATETIME,
    weekly_token_budget INTEGER,
    max_active_jobs INTEGER,
    max_concurrent_runs INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def _legacy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'system.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(_LEGACY_USERS_DDL))
        conn.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, created_at,"
                " updated_at) VALUES ('u1', 'owner', 'pbkdf2:1:00:00', 'admin',"
                " '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    return engine


def _columns(engine, table):
    with engine.begin() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def test_migration_adds_auth_columns_to_a_legacy_users_table(tmp_path):
    engine = _legacy_engine(tmp_path)
    migrate_system_db(engine)
    assert {
        "email",
        "email_verified_at",
        "google_sub",
        "session_epoch",
        "failed_login_count",
        "locked_until",
    } <= _columns(engine, "users")


def test_migration_preserves_the_existing_row_with_null_email(tmp_path):
    engine = _legacy_engine(tmp_path)
    migrate_system_db(engine)
    init_system_db(engine)
    with Session(engine) as session:
        user = session.get(User, "u1")
        assert user is not None
        assert user.email is None
        assert user.session_epoch == 0
        assert user.failed_login_count == 0


def test_migration_is_idempotent(tmp_path):
    engine = _legacy_engine(tmp_path)
    migrate_system_db(engine)
    migrate_system_db(engine)
    assert "email" in _columns(engine, "users")


def test_migration_is_a_no_op_when_users_table_is_absent(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    migrate_system_db(engine)  # must not raise


def test_multiple_users_may_have_no_email(tmp_path):
    engine = _legacy_engine(tmp_path)
    migrate_system_db(engine)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(User(id="u2", username="second", password_hash="x", role="user"))
        session.add(User(id="u3", username="third", password_hash="x", role="user"))
        session.commit()  # NULL is distinct in a SQLite unique index


def test_new_tables_are_created(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    init_system_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            PendingRegistration(
                id="p1",
                email="a@example.com",
                password_hash="h",
                display_name=None,
                invite_code_hash="ih",
                code_hash="ch",
                expires_at=now,
            )
        )
        session.add(
            PasswordResetCode(id="r1", user_id="u1", code_hash="ch", expires_at=now)
        )
        session.add(LoginAttempt(scope="ip", identifier="1.2.3.4", occurred_at=now))
        session.commit()


def test_has_password_reads_the_empty_string_sentinel():
    assert has_password(User(id="u", username="u", password_hash="", role="user")) is False
    assert has_password(User(id="u", username="u", password_hash="pbkdf2:1:a:b", role="user")) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_migrate_system.py -v`
Expected: FAIL — `ImportError: cannot import name 'LoginAttempt'`

- [ ] **Step 3: Extend `tenancy/system_db.py`**

Add to the `User` class body, after `max_concurrent_runs`:

```python
    # Email identity. Nullable so pre-existing rows survive the migration; a
    # NULL email is what the legacy username login fallback keys on. SQLite
    # treats NULL as distinct in a unique index, so any number may coexist.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Google's stable subject id. Email can change; sub cannot — matching an
    # OAuth identity on email alone is an account-takeover vector.
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Mixed into the session HMAC key: bumping it revokes every cookie at once.
    session_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Add after the `InviteCode` class:

```python
class PendingRegistration(SystemBase):
    """A signup awaiting email verification.

    The User row is deliberately NOT created here. Creating it at register
    time means a typo'd address burns a one-time invite and leaves an orphan
    workspace on the volume; nothing is allocated until the address is proven.
    """

    __tablename__ = "pending_registrations"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    invite_code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PasswordResetCode(SystemBase):
    __tablename__ = "password_reset_codes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set when this code adopts a new address for an existing account (Task 13);
    # NULL when it is an ordinary password reset. One row shape, two purposes,
    # distinguished by a real field rather than a sentinel. Every reset query
    # MUST filter `pending_email.is_(None)` or it will consume an adoption row.
    pending_email: Mapped[str | None] = mapped_column(String(320))


class LoginAttempt(SystemBase):
    """Failed authentications only — successes are never recorded.

    One failure writes three rows, one per scope, so the three budgets in
    api/attempts.py are independent counts over the same event.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_scope_id_ts", "scope", "identifier", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier: Mapped[str] = mapped_column(String(400), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


def has_password(user: User) -> bool:
    """password_hash stays NOT NULL; "" is the no-password sentinel.

    SQLite cannot relax NOT NULL via ALTER TABLE, so nullability would force a
    full table rebuild on a live volume for no behavioral gain. verify_password
    already fails closed on "".
    """
    return bool(user.password_hash)
```

- [ ] **Step 4: Write `tenancy/migrate_system.py`**

```python
"""Additive system.db migration.

system.db has no migration runner — init_system_db is a bare create_all, which
adds new *tables* but never new *columns* to an existing one. This copies the
idempotent idiom proven in tracking/migrate.py.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

_USER_COLUMNS = (
    ("email", "VARCHAR(320)"),
    ("email_verified_at", "DATETIME"),
    ("google_sub", "VARCHAR(64)"),
    ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("locked_until", "DATETIME"),
)
_USER_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users (google_sub)",
)
_RESET_COLUMNS = (("pending_email", "VARCHAR(320)"),)


def _add_missing(conn, table: str, columns: tuple[tuple[str, str], ...]) -> None:
    existing = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]
    if not existing:
        return  # table absent; create_all builds the current schema
    for name, ddl in columns:
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def migrate_system_db(engine: Engine) -> None:
    """Idempotently add the auth columns and indexes to existing tables."""
    with engine.begin() as conn:
        users_exist = bool(
            list(conn.execute(text("PRAGMA table_info(users)")))
        )
        _add_missing(conn, "users", _USER_COLUMNS)
        _add_missing(conn, "password_reset_codes", _RESET_COLUMNS)
        if users_exist:
            for statement in _USER_INDEXES:
                conn.execute(text(statement))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_migrate_system.py -v && ruff check src/resume_agent/tenancy`
Expected: 7 passed, ruff clean.

- [ ] **Step 6: Wire the migration into app startup**

In `src/resume_agent/api/app.py`, find the lifespan block where `make_system_engine` is called (~line 113) and add the migration immediately after `init_system_db(system_engine)`:

```python
            from resume_agent.tenancy.migrate_system import migrate_system_db

            migrate_system_db(system_engine)
```

It must run **after** `init_system_db` (so a fresh DB has tables to alter) and **before** `ensure_bootstrapped` (which reads the new columns).

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy tests/api -q`
Expected: all pass — this task changes no behavior.

```bash
git add src/resume_agent/tenancy tests/tenancy/test_migrate_system.py src/resume_agent/api/app.py
git commit -m "Adds email identity columns, code tables, and an additive system.db migration"
```

---

### Task 3: `session_epoch` in the session HMAC

**Files:**

- Modify: `src/resume_agent/api/auth.py:90-141`
- Modify: `src/resume_agent/api/deps.py:_authenticated_user` (~line 110)
- Modify: `src/resume_agent/api/routers/auth.py:104` (the `issue_user_session` call)
- Test: `tests/api/test_session_epoch.py`

**Interfaces:**

- Consumes: `Settings.session_secret`
- Produces:
  - `issue_user_session(settings, *, user_id: str, password_hash: str, epoch: int = 0, now: float | None = None) -> str`
  - `verify_user_session(token, settings, *, password_hash: str, epoch: int = 0, now: float | None = None) -> str | None`
  - `set_session_cookie(request: Request, response: Response, token: str) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_session_epoch.py`:

```python
from resume_agent.api import auth
from resume_agent.config import Settings

SETTINGS = Settings(_env_file=None, session_secret="s3cret")


def test_session_verifies_at_the_epoch_it_was_issued_for():
    token = auth.issue_user_session(
        SETTINGS, user_id="u1", password_hash="hash", epoch=0
    )
    assert auth.verify_user_session(
        token, SETTINGS, password_hash="hash", epoch=0
    ) == "u1"


def test_bumping_the_epoch_invalidates_an_outstanding_session():
    token = auth.issue_user_session(
        SETTINGS, user_id="u1", password_hash="hash", epoch=0
    )
    assert (
        auth.verify_user_session(token, SETTINGS, password_hash="hash", epoch=1) is None
    )


def test_rotating_the_password_hash_still_invalidates_a_session():
    token = auth.issue_user_session(
        SETTINGS, user_id="u1", password_hash="old", epoch=3
    )
    assert (
        auth.verify_user_session(token, SETTINGS, password_hash="new", epoch=3) is None
    )


def test_passwordless_account_gets_a_verifiable_session():
    token = auth.issue_user_session(SETTINGS, user_id="g1", password_hash="", epoch=0)
    assert (
        auth.verify_user_session(token, SETTINGS, password_hash="", epoch=0) == "g1"
    )


def test_two_passwordless_accounts_do_not_share_a_session():
    token = auth.issue_user_session(SETTINGS, user_id="g1", password_hash="", epoch=0)
    assert auth.parse_session_user_id(token) == "g1"
    assert (
        auth.verify_user_session(token, SETTINGS, password_hash="", epoch=0) != "g2"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_session_epoch.py -v`
Expected: FAIL — `TypeError: issue_user_session() got an unexpected keyword argument 'epoch'`

- [ ] **Step 3: Change the signing functions in `api/auth.py`**

Replace `_sign_user`, `issue_user_session`, and `verify_user_session` (lines 90–141) with:

```python
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
```

The key material changes shape (`"session:{hash}"` → `"session:{hash}:{epoch}"`), so every outstanding session cookie is invalidated on deploy. That is acceptable and expected: this change ships alongside the login identifier moving to email, so every user re-authenticates anyway.

- [ ] **Step 4: Add `set_session_cookie` to `api/auth.py`**

Append to `api/auth.py`:

```python
def set_session_cookie(request: Request, response: Response, token: str) -> None:
    """Single owner of the session cookie's flags, shared by every sign-in path."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
```

Add `from fastapi import Request, Response` to the imports at the top of the file.

- [ ] **Step 5: Update the two call sites**

In `api/deps.py::_authenticated_user`, change the `verify_user_session` call (~line 110):

```python
            if candidate is not None and auth_module.verify_user_session(
                cookie,
                request.app.state.settings,
                password_hash=candidate.password_hash,
                epoch=candidate.session_epoch,
            ):
```

In `api/routers/auth.py`, replace the local `_set_session_cookie` helper (lines 49–58) with an import of `auth.set_session_cookie`, and update every call from `_set_session_cookie(...)` to `auth.set_session_cookie(...)`. In the `login` handler, capture the epoch alongside the other fields:

```python
        user_id, username, role, password_hash, epoch = (
            user.id,
            user.username,
            user.role,
            user.password_hash,
            user.session_epoch,
        )
    request.app.state.login_limiter.reset(body.username, _client_ip(request))
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings, user_id=user_id, password_hash=password_hash, epoch=epoch
        ),
    )
```

Also update the `me` handler's `verify_user_session` call (line 216) to pass `epoch=user.session_epoch`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q && ruff check src/resume_agent/api`
Expected: all pass. Any existing test that constructs a session token directly must be updated to pass `epoch=0`; that is the expected fallout, not a regression.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api tests/api/test_session_epoch.py
git commit -m "Mixes session_epoch into the session HMAC so revocation stays table-free"
```

---

**Phase 1 checkpoint.** Run the full backend suite: `.venv/Scripts/python.exe -m pytest -q`. Nothing user-visible has changed; every existing test must still pass.

---

## Phase 2 — Password policy

### Task 4: `password_policy.py` and the breach checker

**Files:**

- Create: `src/resume_agent/api/password_policy.py`
- Create: `src/resume_agent/api/data/common_passwords.txt`
- Test: `tests/api/test_password_policy.py`

**Interfaces:**

- Consumes: `ApiException` from `api/errors.py`
- Produces:
  - `MIN_LENGTH = 12`, `MAX_LENGTH = 1024`
  - `BreachChecker` protocol with `is_breached(password: str) -> bool`
  - `NullBreachChecker()` — always `False`; used by the offline suite
  - `HibpBreachChecker()` — k-anonymity range lookup, fails open
  - `validate_password(password: str, *, email: str, display_name: str | None = None, checker: BreachChecker | None = None) -> None`, raising `ApiException(400, "PASSWORD_WEAK", ...)`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_password_policy.py`:

```python
import hashlib

import httpx
import pytest

from resume_agent.api.errors import ApiException
from resume_agent.api.password_policy import (
    HibpBreachChecker,
    NullBreachChecker,
    validate_password,
)

GOOD = "quartz-lantern-42-drift"


def _weak(password, **kwargs):
    with pytest.raises(ApiException) as excinfo:
        validate_password(password, email="ada@example.com", **kwargs)
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "PASSWORD_WEAK"
    return excinfo.value.message


def test_accepts_a_strong_password():
    validate_password(GOOD, email="ada@example.com")


def test_rejects_a_short_password():
    assert "12 characters" in _weak("short1234")


def test_rejects_a_password_containing_the_email_local_part():
    assert "email" in _weak("ada-is-my-name-here").lower()


def test_rejects_a_password_containing_the_display_name():
    assert "name" in _weak("lovelace-quartz-lantern", display_name="Lovelace").lower()


def test_identity_match_needs_at_least_four_characters():
    validate_password("abc-quartz-lantern-42", email="abc@example.com")


def test_rejects_a_common_password():
    assert "common" in _weak("passwordpassword").lower()


def test_rejects_a_breached_password():
    class AlwaysBreached:
        def is_breached(self, password: str) -> bool:
            return True

    assert "breach" in _weak(GOOD, checker=AlwaysBreached()).lower()


def test_hibp_sends_only_a_five_character_prefix(monkeypatch):
    seen: list[str] = []
    digest = hashlib.sha1(GOOD.encode()).hexdigest().upper()

    def fake_get(url, **kwargs):
        seen.append(url)
        return httpx.Response(200, text=f"{digest[5:]}:42\r\nAAAAA:1")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert HibpBreachChecker().is_breached(GOOD) is True
    assert seen == [f"https://api.pwnedpasswords.com/range/{digest[:5]}"]
    assert GOOD not in seen[0]


def test_hibp_reports_clean_when_the_suffix_is_absent(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda url, **kw: httpx.Response(200, text="0000000:1")
    )
    assert HibpBreachChecker().is_breached(GOOD) is False


def test_hibp_fails_open_on_transport_error(monkeypatch, caplog):
    def explode(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", explode)
    assert HibpBreachChecker().is_breached(GOOD) is False
    assert "failed open" in caplog.text


def test_null_checker_never_reports_breached():
    assert NullBreachChecker().is_breached("password") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_password_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.api.password_policy'`

- [ ] **Step 3: Create the common-password list**

Create `src/resume_agent/api/data/common_passwords.txt` — one lowercase entry per line, no header. Seed it from the SecLists "10-million-password-list-top-1000" (public domain). It must include at least these, which the tests depend on:

```
123456
password
12345678
qwerty
123456789
12345
1234
111111
1234567
dragon
passwordpassword
letmein
monkey
abc123
iloveyou
admin
welcome
login
princess
qwertyuiop
```

Fill to 1000 entries from that list. Entries shorter than `MIN_LENGTH` still matter — the length rule runs first, and this rule catches padded variants such as `passwordpassword`.

- [ ] **Step 4: Write `api/password_policy.py`**

```python
"""The single password validator, shared by register, reset, and change.

Order matters: the cheap local rules run before the network call, so a
password that fails on length never costs an HIBP round-trip.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from resume_agent.api.errors import ApiException

logger = logging.getLogger(__name__)

MIN_LENGTH = 12
MAX_LENGTH = 1024
_MIN_IDENTITY_TOKEN = 4
_COMMON_PATH = Path(__file__).parent / "data" / "common_passwords.txt"
_HIBP_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_HIBP_TIMEOUT_SECONDS = 3.0


class BreachChecker(Protocol):
    def is_breached(self, password: str) -> bool: ...


class NullBreachChecker:
    """Offline default: the suite never reaches the network."""

    def is_breached(self, password: str) -> bool:
        return False


class HibpBreachChecker:
    """k-anonymity lookup: only the first 5 SHA-1 hex characters leave.

    The prefix maps to roughly 800 hashes, so the service cannot identify the
    candidate. Fails open — registration availability beats perfect
    enforcement, and the length and wordlist rules still apply.
    """

    def is_breached(self, password: str) -> bool:
        digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            response = httpx.get(
                _HIBP_URL.format(prefix=prefix), timeout=_HIBP_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("HIBP unreachable; breach check failed open")
            return False
        for line in response.text.splitlines():
            candidate, _, _count = line.partition(":")
            if candidate.strip().upper() == suffix:
                return True
        return False


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    if not _COMMON_PATH.is_file():
        return frozenset()
    return frozenset(
        line.strip().casefold()
        for line in _COMMON_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _contains_identity(password: str, *parts: str | None) -> bool:
    lowered = password.casefold()
    for part in parts:
        token = (part or "").strip().casefold()
        if len(token) >= _MIN_IDENTITY_TOKEN and token in lowered:
            return True
    return False


def _reject(message: str) -> None:
    raise ApiException(400, "PASSWORD_WEAK", message)


def validate_password(
    password: str,
    *,
    email: str,
    display_name: str | None = None,
    checker: BreachChecker | None = None,
) -> None:
    if len(password) < MIN_LENGTH:
        _reject(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        _reject(f"Password must be at most {MAX_LENGTH} characters")
    if _contains_identity(password, email.partition("@")[0], display_name):
        _reject("Password must not contain your email address or name")
    if password.casefold() in _common_passwords():
        _reject("That password is too common — choose something less predictable")
    if (checker or NullBreachChecker()).is_breached(password):
        _reject("That password has appeared in a known data breach")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_password_policy.py -v && ruff check src/resume_agent/api/password_policy.py`
Expected: 11 passed, ruff clean.

- [ ] **Step 6: Make sure the data file ships in the wheel**

Inspect `pyproject.toml` for the build backend's package-data configuration and add the `data/*.txt` glob for the `resume_agent.api` package (setuptools: `[tool.setuptools.package-data]`; hatchling: `[tool.hatch.build.targets.wheel] include`). Then verify the file loads through the package path rather than the repo path:

Run: `.venv/Scripts/python.exe -c "from resume_agent.api.password_policy import _common_passwords; print(len(_common_passwords()))"`
Expected: a number ≥ 1000.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api/password_policy.py src/resume_agent/api/data tests/api/test_password_policy.py pyproject.toml
git commit -m "Adds the password policy with an offline floor and HIBP k-anonymity breach check"
```

---

### Task 5: Wire the policy into change-password

**Files:**

- Modify: `src/resume_agent/api/app.py` (app state, ~line 172)
- Modify: `src/resume_agent/api/routers/account.py` (the `change_password` handler)
- Modify: `tests/api/conftest.py` (the `mu_app` fixture)
- Test: `tests/api/test_account_password.py`

**Interfaces:**

- Consumes: `validate_password`, `build_mailer`, `messages.password_changed`, `auth.set_session_cookie`
- Produces: `app.state.mailer: Mailer`, `app.state.breach_checker: BreachChecker`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_account_password.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resume_agent.api.auth import verify_password
from resume_agent.tenancy.system_db import User

NEW_PASSWORD = "quartz-lantern-42-drift"


def _login(client):
    response = client.post(
        "/api/auth/login", json={"username": "owner", "password": "owner-password"}
    )
    assert response.status_code == 200


def _change(client, new=NEW_PASSWORD, current="owner-password"):
    return client.post(
        "/api/account/password",
        json={"currentPassword": current, "newPassword": new},
    )


def test_change_password_rejects_a_weak_new_password(mu_app):
    with TestClient(mu_app) as client:
        _login(client)
        response = _change(client, new="passwordpassword")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_WEAK"


def test_change_password_rotates_the_hash_and_bumps_the_epoch(mu_app):
    with TestClient(mu_app) as client:
        _login(client)
        assert _change(client).status_code == 200
        # The caller keeps working: the cookie was re-issued at the new epoch.
        assert client.get("/api/auth/me").json()["username"] == "owner"
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter(User.username == "owner").one()
        assert user.session_epoch == 1
        assert verify_password(NEW_PASSWORD, user.password_hash)


def test_change_password_sends_a_notice(mu_app):
    with TestClient(mu_app) as client:
        _login(client)
        _change(client)
    subjects = [subject for _to, subject, _body in mu_app.state.mailer.sent]
    assert any("password was changed" in subject for subject in subjects)


def test_a_stale_cookie_stops_working_after_an_epoch_bump(mu_app):
    with TestClient(mu_app) as client:
        _login(client)
        stale = client.cookies.get("ra_session")
        _change(client)
    with TestClient(mu_app) as other:
        other.cookies.set("ra_session", stale)
        assert other.get("/api/auth/me").json().get("username") is None
```

Note: the notice test needs the owner to have an email. Until Task 10 lands, `user.email` is `None` for the bootstrap admin, so this test must set it first. Add to the test, before `_login`:

```python
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter(User.username == "owner").one()
        user.email = "owner@example.com"
        session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account_password.py -v`
Expected: FAIL — the weak password is accepted and `session_epoch` stays `0`.

- [ ] **Step 3: Build the mailer and checker onto app state**

In `src/resume_agent/api/app.py`, beside the other `app.state` assignments (~line 172), add:

```python
    app.state.mailer = build_mailer(resolved_settings)
    app.state.breach_checker = HibpBreachChecker()
```

with imports at the top:

```python
from resume_agent.api.password_policy import HibpBreachChecker
from resume_agent.mail.mailer import build_mailer
```

- [ ] **Step 4: Make the test fixture offline**

In `tests/api/conftest.py`, in the `mu_app` fixture, capture the app and override both before returning. `create_app` sets them itself, so the override must come **after** the call:

```python
@pytest.fixture
def mu_app(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('owner-password', iterations=1000)}\n"
        "SESSION_SECRET=test-session-secret\n",
        encoding="utf-8",
    )
    application = create_app(
        db_url=f"sqlite:///{(tmp_path / 'data' / 'ignored.db').as_posix()}",
        env_path=env,
        data_dir=tmp_path / "data",
        runs_root=tmp_path / "legacy-runs",
        config_dir=tmp_path / "templates",
    )
    # Offline by construction: no SMTP, no HIBP.
    application.state.mailer = NullMailer()
    application.state.breach_checker = NullBreachChecker()
    return application
```

with `from resume_agent.mail.mailer import NullMailer` and `from resume_agent.api.password_policy import NullBreachChecker` at the top of the conftest.

- [ ] **Step 5: Update the `change_password` handler**

In `src/resume_agent/api/routers/account.py`, replace the `change_password` handler with:

```python
@router.post("/password")
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, context.user_id)
        if user is None or not auth.verify_password(
            body.current_password, user.password_hash
        ):
            raise ApiException(401, "UNAUTHORIZED", "Current password is incorrect")
        validate_password(
            body.new_password,
            email=user.email or "",
            display_name=user.username,
            checker=request.app.state.breach_checker,
        )
        user.password_hash = auth.hash_password(body.new_password)
        # Both the hash and the epoch feed the session HMAC key, so this signs
        # out every other device; the caller's cookie is re-issued below.
        user.session_epoch += 1
        session.commit()
        session.refresh(user)
        email, password_hash, epoch = (
            user.email,
            user.password_hash,
            user.session_epoch,
        )
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings, user_id=context.user_id, password_hash=password_hash, epoch=epoch
        ),
    )
    if email:
        message = messages.password_changed(settings.app_base_url)
        request.app.state.mailer.notify(
            to=email, subject=message.subject, body=message.body
        )
    return {"status": "ok"}
```

Add these imports to `account.py`:

```python
from resume_agent.api.password_policy import validate_password
from resume_agent.mail import messages
```

`notify` (not `send`) is correct: the hash rotation has already committed, so a dead SMTP host must not fail the request.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q && ruff check src/resume_agent/api`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api tests/api
git commit -m "Applies the password policy, epoch bump, and change notice to change-password"
```

---

## Phase 3 — Durable rate limiting and lockout

### Task 6: `api/attempts.py`

**Files:**

- Create: `src/resume_agent/api/attempts.py`
- Test: `tests/api/test_attempts.py`

**Interfaces:**

- Consumes: `LoginAttempt`, `User` from `tenancy/system_db.py`
- Produces:
  - `Budget(scope: str, limit: int, window: timedelta)` frozen dataclass
  - `BUDGETS: tuple[Budget, ...]`, `IP_ONLY: frozenset[str]`
  - `blocked(engine, *, email: str, ip: str, scopes: frozenset[str] | None = None, now: datetime | None = None) -> bool`
  - `record_failure(engine, *, email: str, ip: str, now: datetime | None = None) -> None`
  - `reset(engine, *, email: str, ip: str) -> None`
  - `register_lockout(user: User, now: datetime) -> None`
  - `clear_lockout(user: User) -> None`
  - `is_locked(user: User, now: datetime) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_attempts.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from resume_agent.api import attempts
from resume_agent.tenancy.system_db import LoginAttempt, User, init_system_db

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'system.db').as_posix()}")
    init_system_db(engine)
    return engine


def _fail(engine, times, *, email="a@example.com", ip="1.2.3.4", now=NOW):
    for offset in range(times):
        attempts.record_failure(
            engine, email=email, ip=ip, now=now + timedelta(seconds=offset)
        )


def test_email_ip_budget_trips_at_ten(tmp_path):
    engine = _engine(tmp_path)
    _fail(engine, 9)
    assert attempts.blocked(engine, email="a@example.com", ip="1.2.3.4", now=NOW) is False
    _fail(engine, 1)
    assert attempts.blocked(engine, email="a@example.com", ip="1.2.3.4", now=NOW) is True


def test_rotating_the_ip_still_trips_the_email_budget(tmp_path):
    engine = _engine(tmp_path)
    for index in range(20):
        attempts.record_failure(
            engine, email="a@example.com", ip=f"10.0.0.{index}", now=NOW
        )
    # A fresh IP clears email_ip, but the email budget is exhausted.
    assert attempts.blocked(engine, email="a@example.com", ip="10.0.0.99", now=NOW) is True


def test_spraying_many_accounts_trips_the_ip_budget(tmp_path):
    engine = _engine(tmp_path)
    for index in range(50):
        attempts.record_failure(
            engine, email=f"u{index}@example.com", ip="9.9.9.9", now=NOW
        )
    assert attempts.blocked(engine, email="fresh@example.com", ip="9.9.9.9", now=NOW) is True


def test_attempts_outside_the_window_do_not_count(tmp_path):
    engine = _engine(tmp_path)
    _fail(engine, 10, now=NOW - timedelta(minutes=30))
    assert attempts.blocked(engine, email="a@example.com", ip="1.2.3.4", now=NOW) is False


def test_reset_clears_email_scopes_but_not_the_ip_budget(tmp_path):
    engine = _engine(tmp_path)
    for index in range(50):
        attempts.record_failure(
            engine, email=f"u{index}@example.com", ip="9.9.9.9", now=NOW
        )
    attempts.reset(engine, email="u0@example.com", ip="9.9.9.9")
    # A successful login must not hand an attacker back their spraying budget.
    assert attempts.blocked(engine, email="u0@example.com", ip="9.9.9.9", now=NOW) is True


def test_ip_only_scope_ignores_the_email_budgets(tmp_path):
    engine = _engine(tmp_path)
    _fail(engine, 25)
    assert (
        attempts.blocked(
            engine,
            email="a@example.com",
            ip="1.2.3.4",
            scopes=attempts.IP_ONLY,
            now=NOW,
        )
        is False
    )


def test_email_matching_is_case_insensitive(tmp_path):
    engine = _engine(tmp_path)
    _fail(engine, 10, email="A@Example.COM")
    assert attempts.blocked(engine, email="a@example.com", ip="1.2.3.4", now=NOW) is True


def test_pruning_keeps_the_table_bounded(tmp_path):
    engine = _engine(tmp_path)
    _fail(engine, 3, now=NOW - timedelta(days=2))
    attempts.record_failure(engine, email="a@example.com", ip="1.2.3.4", now=NOW)
    with Session(engine) as session:
        count = session.execute(
            select(func.count()).select_from(LoginAttempt)
        ).scalar_one()
    assert count == 3  # only the current failure's three scope rows survive


def _user() -> User:
    return User(id="u1", username="u", password_hash="h", role="user")


def test_lockout_tiers_escalate():
    user = _user()
    for _ in range(4):
        attempts.register_lockout(user, NOW)
    assert user.locked_until is None
    attempts.register_lockout(user, NOW)  # 5th
    assert user.locked_until == NOW + timedelta(minutes=1)
    for _ in range(5):
        attempts.register_lockout(user, NOW)  # 10th
    assert user.locked_until == NOW + timedelta(minutes=15)
    for _ in range(5):
        attempts.register_lockout(user, NOW)  # 15th
    assert user.locked_until == NOW + timedelta(hours=1)


def test_failures_between_tiers_do_not_extend_the_lock():
    user = _user()
    for _ in range(5):
        attempts.register_lockout(user, NOW)
    attempts.register_lockout(user, NOW + timedelta(minutes=10))  # 6th
    assert user.locked_until == NOW + timedelta(minutes=1)


def test_clear_lockout_resets_both_fields():
    user = _user()
    for _ in range(5):
        attempts.register_lockout(user, NOW)
    attempts.clear_lockout(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert attempts.is_locked(user, NOW) is False


def test_is_locked_treats_a_naive_timestamp_as_utc():
    user = _user()
    user.locked_until = datetime(2026, 7, 28, 13, 0)  # naive, as SQLite returns
    assert attempts.is_locked(user, NOW) is True
```

Note: `User()` constructed outside a session leaves `failed_login_count` as `None` because SQLAlchemy column defaults apply at flush. `register_lockout` must therefore tolerate `None`; the implementation below reads it via `or 0`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_attempts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.api.attempts'`

- [ ] **Step 3: Write `api/attempts.py`**

```python
"""Durable rate-limit budgets and progressive account lockout.

The previous in-memory FailedAttemptLimiter keyed on (username, ip) in process
memory. Two gaps: rotating the source IP produced a fresh key, so a distributed
attempt on one account never tripped it; and counters died on restart, so a
redeploy handed an attacker a clean budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import LoginAttempt, User


@dataclass(frozen=True)
class Budget:
    scope: str
    limit: int
    window: timedelta


BUDGETS: tuple[Budget, ...] = (
    Budget("email_ip", 10, timedelta(minutes=15)),
    Budget("email", 20, timedelta(hours=1)),
    Budget("ip", 50, timedelta(hours=1)),
)
IP_ONLY = frozenset({"ip"})
_MAX_WINDOW = max(budget.window for budget in BUDGETS)

# Consecutive-failure thresholds, checked high to low. Every 5th failure at or
# beyond 15 re-locks for an hour.
_LOCK_TIERS: tuple[tuple[int, timedelta], ...] = (
    (15, timedelta(hours=1)),
    (10, timedelta(minutes=15)),
    (5, timedelta(minutes=1)),
)
_TIER_STRIDE = 5


def _identifiers(email: str, ip: str) -> dict[str, str]:
    folded = email.casefold()
    return {"email_ip": f"{folded}|{ip}", "email": folded, "ip": ip}


def blocked(
    engine: Engine,
    *,
    email: str,
    ip: str,
    scopes: frozenset[str] | None = None,
    now: datetime | None = None,
) -> bool:
    moment = now or datetime.now(timezone.utc)
    identifiers = _identifiers(email, ip)
    with Session(engine) as session:
        for budget in BUDGETS:
            if scopes is not None and budget.scope not in scopes:
                continue
            count = session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(
                    LoginAttempt.scope == budget.scope,
                    LoginAttempt.identifier == identifiers[budget.scope],
                    LoginAttempt.occurred_at > moment - budget.window,
                )
            ).scalar_one()
            if count >= budget.limit:
                return True
    return False


def record_failure(
    engine: Engine, *, email: str, ip: str, now: datetime | None = None
) -> None:
    """Write one row per scope, pruning anything past the longest window."""
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        session.execute(
            delete(LoginAttempt).where(LoginAttempt.occurred_at < moment - _MAX_WINDOW)
        )
        for scope, identifier in _identifiers(email, ip).items():
            session.add(
                LoginAttempt(scope=scope, identifier=identifier, occurred_at=moment)
            )
        session.commit()


def reset(engine: Engine, *, email: str, ip: str) -> None:
    """Clear the email-bound budgets on success.

    The ip budget is deliberately NOT cleared: otherwise an attacker holding
    one valid account could wipe their spraying budget at will.
    """
    identifiers = _identifiers(email, ip)
    with Session(engine) as session:
        for scope in ("email_ip", "email"):
            session.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.scope == scope,
                    LoginAttempt.identifier == identifiers[scope],
                )
            )
        session.commit()


def register_lockout(user: User, now: datetime) -> None:
    """Count one failure and, at a tier boundary, lock the account."""
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count % _TIER_STRIDE:
        return
    for threshold, duration in _LOCK_TIERS:
        if user.failed_login_count >= threshold:
            user.locked_until = now + duration
            return


def clear_lockout(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None


def is_locked(user: User, now: datetime) -> bool:
    until = user.locked_until
    if until is None:
        return False
    if until.tzinfo is None:  # SQLite hands back naive datetimes
        until = until.replace(tzinfo=timezone.utc)
    return until > now
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_attempts.py -v && ruff check src/resume_agent/api/attempts.py`
Expected: 12 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/attempts.py tests/api/test_attempts.py
git commit -m "Adds durable three-scope rate limiting and progressive account lockout"
```

---

### Task 7: Replace the in-memory limiter at the login call site

**Files:**

- Modify: `src/resume_agent/api/routers/auth.py` (lines 31–47 and the `login` handler)
- Modify: `src/resume_agent/api/app.py` (drop `app.state.login_limiter`)
- Delete: `src/resume_agent/api/rate_limit.py`
- Test: `tests/api/test_login_lockout.py`

**Interfaces:**

- Consumes: `api.attempts`
- Produces, in `routers/auth.py`:
  - `_rate_gate(request: Request, identifier: str, *, scopes: frozenset[str] | None = None) -> None`
  - `_record_failure(request: Request, identifier: str) -> None`
  - `_clear_failures(request: Request, identifier: str) -> None`

  These three are reused verbatim by the Phase 4 and Phase 5 routers, so keep them module-level and non-underscore-private to the package (import as `from resume_agent.api.routers.auth import _rate_gate` is acceptable within `api/routers/`).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_login_lockout.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import User


def _bad_login(client, times=1):
    response = None
    for _ in range(times):
        response = client.post(
            "/api/auth/login", json={"username": "owner", "password": "wrong"}
        )
    return response


def test_repeated_failures_eventually_rate_limit(mu_app):
    with TestClient(mu_app) as client:
        response = _bad_login(client, times=11)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_five_failures_lock_the_account(mu_app):
    with TestClient(mu_app) as client:
        _bad_login(client, times=5)
        with Session(mu_app.state.system_engine) as session:
            user = session.query(User).filter(User.username == "owner").one()
            assert user.failed_login_count == 5
            assert user.locked_until is not None
        # A locked account is indistinguishable from a wrong password.
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_a_successful_login_clears_the_counters(mu_app):
    with TestClient(mu_app) as client:
        _bad_login(client, times=3)
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password"},
        )
        assert response.status_code == 200
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter(User.username == "owner").one()
        assert user.failed_login_count == 0
        assert user.locked_until is None


def test_failures_survive_an_app_restart(mu_app):
    with TestClient(mu_app) as client:
        _bad_login(client, times=10)
    with TestClient(mu_app) as client:  # lifespan runs again
        response = client.post(
            "/api/auth/login", json={"username": "owner", "password": "wrong"}
        )
    assert response.status_code == 429


def test_an_unknown_account_is_rate_limited_without_a_user_row(mu_app):
    with TestClient(mu_app) as client:
        response = None
        for _ in range(11):
            response = client.post(
                "/api/auth/login", json={"username": "ghost", "password": "wrong"}
            )
    assert response.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_login_lockout.py -v`
Expected: FAIL — `failed_login_count` stays `0`, and the restart test returns 401 rather than 429.

- [ ] **Step 3: Rewrite the gate helpers in `routers/auth.py`**

Replace `_rate_gate` and `_record_failure` (lines 38–47) with:

```python
def _system_engine(request: Request):
    return getattr(request.app.state, "system_engine", None)


def _rate_gate(
    request: Request, identifier: str, *, scopes: frozenset[str] | None = None
) -> None:
    engine = _system_engine(request)
    if engine is None:  # legacy single-account mode has no system.db
        return
    if attempts.blocked(engine, email=identifier, ip=_client_ip(request), scopes=scopes):
        raise ApiException(
            429, "RATE_LIMITED", "Too many failed attempts; try again later"
        )


def _record_failure(request: Request, identifier: str) -> None:
    engine = _system_engine(request)
    if engine is not None:
        attempts.record_failure(engine, email=identifier, ip=_client_ip(request))


def _clear_failures(request: Request, identifier: str) -> None:
    engine = _system_engine(request)
    if engine is not None:
        attempts.reset(engine, email=identifier, ip=_client_ip(request))
```

Add `from resume_agent.api import attempts` to the imports.

- [ ] **Step 4: Apply the lockout inside the `login` handler**

Inside `login`'s `with Session(system_engine) as session:` block, replace everything from the `password_valid` computation through `session.commit()` with:

```python
        password_valid = auth.verify_password(body.password, password_hash)
        now = datetime.now(timezone.utc)
        locked = user is not None and attempts.is_locked(user, now)
        if user is None or not password_valid or locked:
            if user is not None and not locked:
                attempts.register_lockout(user, now)
                session.commit()
            _record_failure(request, body.username)
            time.sleep(FAILED_LOGIN_DELAY_SECONDS)
            # A locked account returns the same generic error as a wrong
            # password: disclosing the lock tells an attacker their guesses
            # are landing on a real account.
            raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
        if user.disabled_at is not None:
            _record_failure(request, body.username)
            raise ApiException(403, "USER_DISABLED", "This account is disabled")
        if auth.hash_needs_upgrade(user.password_hash):
            user.password_hash = auth.hash_password(body.password)
        attempts.clear_lockout(user)
        user.last_active_at = now
        session.commit()
        session.refresh(user)
```

Replace the `request.app.state.login_limiter.reset(...)` line after the block with `_clear_failures(request, body.username)`.

- [ ] **Step 5: Remove the old limiter**

Delete `src/resume_agent/api/rate_limit.py` and any `tests/api/test_rate_limit.py`. In `api/app.py`, delete the `app.state.login_limiter = FailedAttemptLimiter()` line and its import. Confirm nothing references it:

Run: `grep -rn "login_limiter\|FailedAttemptLimiter" src tests`
Expected: no output.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q && ruff check src/resume_agent/api`
Expected: all pass. The `register` handler still calls `_rate_gate(request, body.username)` — the new signature is compatible.

- [ ] **Step 7: Commit**

```bash
git add -A src/resume_agent/api tests/api
git commit -m "Replaces the in-memory login limiter with durable budgets and account lockout"
```

---

**Phase 3 checkpoint.** Run `.venv/Scripts/python.exe -m pytest -q` and `ruff check`. Login is hardened, but the identifier is still `username` — the wire contract has not changed yet.

---

## Phase 4 — Email registration and reset

### Task 8: Code generation and verification helper

**Files:**

- Create: `src/resume_agent/api/auth_codes.py`
- Test: `tests/api/test_auth_codes.py`

**Interfaces:**

- Consumes: `Settings.session_secret`
- Produces:
  - `CODE_TTL = timedelta(minutes=15)`, `MAX_ATTEMPTS = 5`
  - `generate_code() -> str` — six digits, zero-padded
  - `hash_code(code: str, settings: Settings) -> str`
  - `expires_at(now: datetime | None = None) -> datetime`
  - `CodeRow` protocol — anything with `code_hash: str`, `expires_at: datetime`, `attempts: int`
  - `check_code(row: CodeRow, code: str, settings: Settings, *, now: datetime | None = None) -> CodeVerdict`
  - `CodeVerdict` enum: `OK`, `INVALID`, `EXPIRED`, `EXHAUSTED`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_codes.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from resume_agent.api import auth_codes
from resume_agent.config import Settings

SETTINGS = Settings(_env_file=None, session_secret="s3cret")
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


@dataclass
class Row:
    code_hash: str
    expires_at: datetime
    attempts: int = 0


def _row(code="123456", *, expires=None, attempts=0):
    return Row(
        code_hash=auth_codes.hash_code(code, SETTINGS),
        expires_at=expires or NOW + timedelta(minutes=10),
        attempts=attempts,
    )


def test_generated_code_is_six_digits():
    for _ in range(50):
        code = auth_codes.generate_code()
        assert len(code) == 6
        assert code.isdigit()


def test_hash_is_stable_and_secret_dependent():
    other = Settings(_env_file=None, session_secret="different")
    assert auth_codes.hash_code("123456", SETTINGS) == auth_codes.hash_code("123456", SETTINGS)
    assert auth_codes.hash_code("123456", SETTINGS) != auth_codes.hash_code("123456", other)
    assert "123456" not in auth_codes.hash_code("123456", SETTINGS)


def test_correct_code_verifies():
    row = _row()
    assert auth_codes.check_code(row, "123456", SETTINGS, now=NOW) is auth_codes.CodeVerdict.OK


def test_wrong_code_is_invalid_and_counts_an_attempt():
    row = _row()
    assert (
        auth_codes.check_code(row, "000000", SETTINGS, now=NOW)
        is auth_codes.CodeVerdict.INVALID
    )
    assert row.attempts == 1


def test_correct_code_does_not_count_an_attempt():
    row = _row()
    auth_codes.check_code(row, "123456", SETTINGS, now=NOW)
    assert row.attempts == 0


def test_expired_code_is_rejected_without_counting():
    row = _row(expires=NOW - timedelta(seconds=1))
    assert (
        auth_codes.check_code(row, "123456", SETTINGS, now=NOW)
        is auth_codes.CodeVerdict.EXPIRED
    )
    assert row.attempts == 0


def test_fifth_wrong_attempt_exhausts_the_code():
    row = _row(attempts=4)
    assert (
        auth_codes.check_code(row, "000000", SETTINGS, now=NOW)
        is auth_codes.CodeVerdict.EXHAUSTED
    )


def test_an_exhausted_code_rejects_even_the_correct_value():
    row = _row(attempts=5)
    assert (
        auth_codes.check_code(row, "123456", SETTINGS, now=NOW)
        is auth_codes.CodeVerdict.EXHAUSTED
    )


def test_naive_expiry_from_sqlite_is_treated_as_utc():
    row = _row(expires=datetime(2026, 7, 28, 12, 10))
    assert auth_codes.check_code(row, "123456", SETTINGS, now=NOW) is auth_codes.CodeVerdict.OK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_codes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.api.auth_codes'`

- [ ] **Step 3: Write `api/auth_codes.py`**

```python
"""Six-digit codes for email verification and password reset.

Six digits is 10^6 — brute-forceable in seconds against an unthrottled
endpoint. MAX_ATTEMPTS is the primary defense; the endpoint rate limits in
api/attempts.py are the backstop. Both are required.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from resume_agent.config import Settings

CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5
_CODE_CEILING = 1_000_000


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
    return f"{secrets.randbelow(_CODE_CEILING):06d}"


def hash_code(code: str, settings: Settings) -> str:
    """Peppered with session_secret so a stolen DB alone cannot replay codes."""
    return hashlib.sha256(f"{code}:{settings.session_secret}".encode("utf-8")).hexdigest()


def expires_at(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + CODE_TTL


def check_code(
    row: CodeRow, code: str, settings: Settings, *, now: datetime | None = None
) -> CodeVerdict:
    """Verify a submitted code, mutating row.attempts on a wrong guess.

    The caller owns the transaction: it must commit for the attempt count to
    persist, and delete the row on EXHAUSTED.
    """
    moment = now or datetime.now(timezone.utc)
    if row.attempts >= MAX_ATTEMPTS:
        return CodeVerdict.EXHAUSTED
    deadline = row.expires_at
    if deadline.tzinfo is None:  # SQLite hands back naive datetimes
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= moment:
        return CodeVerdict.EXPIRED
    if hmac.compare_digest(row.code_hash, hash_code(code, settings)):
        return CodeVerdict.OK
    row.attempts += 1
    return CodeVerdict.EXHAUSTED if row.attempts >= MAX_ATTEMPTS else CodeVerdict.INVALID
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_codes.py -v && ruff check src/resume_agent/api/auth_codes.py`
Expected: 9 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/auth_codes.py tests/api/test_auth_codes.py
git commit -m "Adds peppered six-digit codes with TTL and attempt exhaustion"
```

---

### Task 9: Registration schemas and the register endpoint

**Files:**

- Create: `src/resume_agent/api/schemas/auth_email.py`
- Create: `src/resume_agent/api/routers/auth_register.py`
- Modify: `src/resume_agent/api/app.py` (mount the router, unguarded, next to `auth_router.router`)
- Test: `tests/api/test_auth_register.py`

**Interfaces:**

- Consumes: `auth_codes`, `password_policy.validate_password`, `attempts`, `mail.messages`, `PendingRegistration`, `InviteCode`, `User`, `hash_secret`
- Produces:
  - `RegisterRequest(email: EmailStr, password: str, invite_code: str, display_name: str | None)`
  - `VerifyEmailRequest(email: EmailStr, code: str)`
  - `ResendCodeRequest(email: EmailStr)`
  - `CodeSentResponse(status: Literal["sent"])`
  - `router: APIRouter` with prefix `/auth`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_register.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, PendingRegistration, User

PASSWORD = "quartz-lantern-42-drift"
SENT = {"status": "sent"}


def _mint_invite(app, code="inv_testcode123"):
    from datetime import datetime, timedelta, timezone

    with Session(app.state.system_engine) as session:
        session.add(
            InviteCode(
                id="i1",
                code_hash=hash_secret(code),
                created_by="u1",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
        session.commit()
    return code


def _register(client, invite, email="ada@example.com", password=PASSWORD):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "inviteCode": invite,
            "displayName": "Ada",
        },
    )


def _codes(app):
    return [body for _to, _subject, body in app.state.mailer.sent]


def test_register_returns_202_and_creates_no_user(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        response = _register(client, invite)
    assert response.status_code == 202
    assert response.json() == SENT
    with Session(mu_app.state.system_engine) as session:
        assert session.execute(
            select(User).where(User.email == "ada@example.com")
        ).first() is None
        pending = session.execute(select(PendingRegistration)).scalars().one()
        assert pending.email == "ada@example.com"


def test_register_does_not_consume_the_invite(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
    with Session(mu_app.state.system_engine) as session:
        assert session.get(InviteCode, "i1").used_at is None


def test_register_never_returns_the_code(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        response = _register(client, invite)
    code = _codes(mu_app)[0]
    digits = "".join(character for character in code if character.isdigit())[:6]
    assert digits not in response.text


def test_register_rejects_an_unknown_invite(mu_app):
    with TestClient(mu_app) as client:
        response = _register(client, "inv_nope")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVITE_INVALID"


def test_register_rejects_a_weak_password(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        response = _register(client, invite, password="passwordpassword")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_WEAK"


def test_register_on_an_existing_address_is_indistinguishable(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        with Session(mu_app.state.system_engine) as session:
            user = session.query(User).filter(User.username == "owner").one()
            user.email = "ada@example.com"
            session.commit()
        response = _register(client, invite)
    assert response.status_code == 202
    assert response.json() == SENT
    subjects = [subject for _to, subject, _body in mu_app.state.mailer.sent]
    assert any("tried to sign up" in subject for subject in subjects)
    with Session(mu_app.state.system_engine) as session:
        assert session.execute(select(PendingRegistration)).first() is None


def test_re_registering_replaces_the_pending_row(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        _register(client, invite)
    with Session(mu_app.state.system_engine) as session:
        assert len(session.execute(select(PendingRegistration)).scalars().all()) == 1


def test_email_is_stored_casefolded(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite, email="Ada@Example.COM")
    with Session(mu_app.state.system_engine) as session:
        assert session.execute(select(PendingRegistration)).scalars().one().email == "ada@example.com"


def test_register_fails_loudly_when_mail_cannot_be_delivered(mu_app):
    from resume_agent.mail.mailer import MailDeliveryError

    class DeadMailer:
        def send(self, **kwargs):
            raise MailDeliveryError("smtp down")

        def notify(self, **kwargs):
            pass

    mu_app.state.mailer = DeadMailer()
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        response = _register(client, invite)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MAIL_UNAVAILABLE"
    with Session(mu_app.state.system_engine) as session:
        # The pending row must be rolled back, not left orphaned.
        assert session.execute(select(PendingRegistration)).first() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_register.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Write `api/schemas/auth_email.py`**

```python
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from resume_agent.api.schemas.base import CamelModel


class _EmailBody(CamelModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class RegisterRequest(_EmailBody):
    password: str = Field(min_length=1, max_length=1024)
    invite_code: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)


class VerifyEmailRequest(_EmailBody):
    code: str = Field(pattern=r"^\d{6}$")


class ResendCodeRequest(_EmailBody):
    pass


class ForgotPasswordRequest(_EmailBody):
    pass


class ResetPasswordRequest(_EmailBody):
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=1, max_length=1024)


class CodeSentResponse(CamelModel):
    status: Literal["sent"] = "sent"
```

`password` is `min_length=1`, not 12: length is the policy's job, so a short
password gets the same structured `PASSWORD_WEAK` message as a breached one
rather than an unhelpful 422 from Pydantic.

- [ ] **Step 4: Write `api/routers/auth_register.py`**

```python
"""Registration: pending row, emailed code, then account creation.

The User row is deliberately not created by /register. Creating it there means
a typo'd address burns a one-time invite and leaves an orphan workspace on the
volume; invites are the budget control on a shared LLM key, so nothing is
allocated until the address is proven reachable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from resume_agent.api import attempts, auth, auth_codes
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.password_policy import validate_password
from resume_agent.api.schemas.auth import MeResponse
from resume_agent.api.schemas.auth_email import (
    CodeSentResponse,
    RegisterRequest,
    ResendCodeRequest,
    VerifyEmailRequest,
)
from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.mail.mailer import MailDeliveryError
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, PendingRegistration, User
from resume_agent.tenancy.workspace import provision_workspace

router = APIRouter(prefix="/auth", tags=["auth"])

_RESEND_LIMIT = 3


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_multi_user(request: Request):
    engine = getattr(request.app.state, "system_engine", None)
    if engine is None:
        raise ApiException(
            400, "AUTH_NOT_CONFIGURED", "Registration requires multi-user mode"
        )
    return engine


def _rate_gate(request: Request, email: str) -> None:
    engine = _require_multi_user(request)
    if attempts.blocked(engine, email=email, ip=_client_ip(request)):
        raise ApiException(
            429, "RATE_LIMITED", "Too many attempts; try again later"
        )


def _record_failure(request: Request, email: str) -> None:
    engine = getattr(request.app.state, "system_engine", None)
    if engine is not None:
        attempts.record_failure(engine, email=email, ip=_client_ip(request))


def _valid_invite(session: Session, request: Request, code: str) -> InviteCode:
    """Invite validity is not enumeration-sensitive: the caller holds the secret."""
    invite = (
        session.execute(
            select(InviteCode).where(InviteCode.code_hash == hash_secret(code))
        )
        .scalars()
        .first()
    )
    if invite is None or invite.revoked_at is not None:
        raise ApiException(400, "INVITE_INVALID", "Unknown invitation code")
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise ApiException(400, "INVITE_EXPIRED", "Invitation code expired")
    if invite.used_at is not None:
        raise ApiException(400, "INVITE_USED", "Invitation code already used")
    return invite


def _send_or_fail(request: Request, to: str, message: messages.Message) -> None:
    try:
        request.app.state.mailer.send(
            to=to, subject=message.subject, body=message.body
        )
    except MailDeliveryError as error:
        raise ApiException(
            503, "MAIL_UNAVAILABLE", "Could not send the verification email"
        ) from error


@router.post("/register", status_code=202, response_model=CodeSentResponse)
def register(
    body: RegisterRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    engine = _require_multi_user(request)
    _rate_gate(request, body.email)
    with Session(engine) as session:
        _valid_invite(session, request, body.invite_code)
        validate_password(
            body.password,
            email=body.email,
            display_name=body.display_name,
            checker=request.app.state.breach_checker,
        )
        taken = session.execute(
            select(User.id).where(User.email == body.email)
        ).first()
        if taken is not None:
            # Same status and body as a fresh signup — the holder learns by
            # email, a stranger learns nothing.
            notice = messages.signup_on_existing(settings.app_base_url)
            request.app.state.mailer.notify(
                to=body.email, subject=notice.subject, body=notice.body
            )
            return CodeSentResponse()
        code = auth_codes.generate_code()
        session.execute(
            delete(PendingRegistration).where(
                PendingRegistration.email == body.email
            )
        )
        session.add(
            PendingRegistration(
                id=uuid.uuid4().hex[:12],
                email=body.email,
                password_hash=auth.hash_password(body.password),
                display_name=body.display_name,
                invite_code_hash=hash_secret(body.invite_code),
                code_hash=auth_codes.hash_code(code, settings),
                expires_at=auth_codes.expires_at(),
            )
        )
        session.flush()
        _send_or_fail(request, body.email, messages.verification_code(code))
        session.commit()  # only after delivery — a failed send rolls back
    return CodeSentResponse()
```

- [ ] **Step 5: Mount the router**

In `api/app.py`, beside the existing unguarded auth router (~line 254):

```python
    app.include_router(auth_register_router.router, prefix="/api")
```

with `from resume_agent.api.routers import auth_register as auth_register_router` at the top.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_register.py -v && ruff check src/resume_agent/api`
Expected: 9 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api tests/api/test_auth_register.py
git commit -m "Adds registration that emails a code without creating the account"
```

---

### Task 10: Verify-email and resend-code

**Files:**

- Modify: `src/resume_agent/api/routers/auth_register.py` (append two handlers)
- Test: `tests/api/test_auth_verify_email.py`

**Interfaces:**

- Consumes: everything from Task 9
- Produces: `POST /api/auth/verify-email -> MeResponse`, `POST /api/auth/resend-code -> CodeSentResponse`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_verify_email.py`:

```python
import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, PendingRegistration, User

PASSWORD = "quartz-lantern-42-drift"
EMAIL = "ada@example.com"


def _mint_invite(app, code="inv_testcode123", invite_id="i1"):
    from datetime import datetime, timedelta, timezone

    with Session(app.state.system_engine) as session:
        session.add(
            InviteCode(
                id=invite_id,
                code_hash=hash_secret(code),
                created_by="u1",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
        session.commit()
    return code


def _last_code(app):
    return re.search(r"\b(\d{6})\b", app.state.mailer.sent[-1][2]).group(1)


def _register(client, invite, email=EMAIL):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "inviteCode": invite},
    )


def test_verifying_creates_the_user_and_signs_in(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        response = client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": _last_code(mu_app)}
        )
        assert response.status_code == 200
        assert response.json()["email"] == EMAIL
        assert client.get("/api/auth/me").json()["email"] == EMAIL
    with Session(mu_app.state.system_engine) as session:
        user = session.execute(select(User).where(User.email == EMAIL)).scalars().one()
        assert user.email_verified_at is not None
        assert user.role == "user"
        assert session.get(InviteCode, "i1").used_by == user.id
        assert session.execute(select(PendingRegistration)).first() is None


def test_verifying_provisions_a_workspace(mu_app, tmp_path):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": _last_code(mu_app)}
        )
    with Session(mu_app.state.system_engine) as session:
        user = session.execute(select(User).where(User.email == EMAIL)).scalars().one()
    assert (mu_app.state.data_dir / "users" / user.id).is_dir()


def test_a_wrong_code_is_rejected(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        response = client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": "000000"}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CODE_INVALID"


def test_five_wrong_codes_destroy_the_pending_row(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        for _ in range(5):
            client.post("/api/auth/verify-email", json={"email": EMAIL, "code": "000000"})
        # Even the correct code no longer works.
        response = client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": _last_code(mu_app)}
        )
    assert response.status_code == 400
    with Session(mu_app.state.system_engine) as session:
        assert session.execute(select(PendingRegistration)).first() is None


def test_verifying_an_unknown_email_is_rejected(mu_app):
    with TestClient(mu_app) as client:
        response = client.post(
            "/api/auth/verify-email", json={"email": "ghost@example.com", "code": "123456"}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CODE_INVALID"


def test_an_invite_spent_between_register_and_verify_is_caught(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        code = _last_code(mu_app)
        with Session(mu_app.state.system_engine) as session:
            from datetime import datetime, timezone

            spent = session.get(InviteCode, "i1")
            spent.used_at = datetime.now(timezone.utc)
            spent.used_by = "someone"
            session.commit()
        response = client.post(
            "/api/auth/verify-email", json={"email": EMAIL, "code": code}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVITE_USED"


def test_resend_issues_a_new_code_and_resets_attempts(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        first = _last_code(mu_app)
        client.post("/api/auth/verify-email", json={"email": EMAIL, "code": "000000"})
        assert client.post("/api/auth/resend-code", json={"email": EMAIL}).status_code == 202
        second = _last_code(mu_app)
        assert first != second
        assert (
            client.post(
                "/api/auth/verify-email", json={"email": EMAIL, "code": second}
            ).status_code
            == 200
        )


def test_resend_for_an_unknown_email_still_returns_202(mu_app):
    with TestClient(mu_app) as client:
        response = client.post("/api/auth/resend-code", json={"email": "ghost@example.com"})
    assert response.status_code == 202
    assert response.json() == {"status": "sent"}
    assert mu_app.state.mailer.sent == []


def test_resend_is_capped_at_three_per_hour(mu_app):
    with TestClient(mu_app) as client:
        invite = _mint_invite(mu_app)
        _register(client, invite)
        for _ in range(3):
            client.post("/api/auth/resend-code", json={"email": EMAIL})
        response = client.post("/api/auth/resend-code", json={"email": EMAIL})
    assert response.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_verify_email.py -v`
Expected: FAIL — 404 for both new routes.

- [ ] **Step 3: Expand `MeResponse` before anything returns the new fields**

`verify-email` is the first endpoint to answer with an email, so the schema
grows here rather than in Task 11. In `api/schemas/auth.py`, replace
`MeResponse` with:

```python
class MeResponse(CamelModel):
    username: str | None = None
    email: str | None = None
    email_verified: bool = False
    # True only for accounts that predate email identity; drives the
    # /complete-profile gate. Deletable once every row has an email.
    needs_email: bool = False
    google_linked: bool = False
    role: Literal["admin", "user"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    auth_required: bool = False
```

Every field defaults, so the existing `login` and `me` handlers keep compiling
untouched — Task 11 is what makes them populate the new fields.

- [ ] **Step 4: Append the handlers to `api/routers/auth_register.py`**

```python
def _pending(session: Session, email: str) -> PendingRegistration | None:
    return (
        session.execute(
            select(PendingRegistration).where(PendingRegistration.email == email)
        )
        .scalars()
        .first()
    )


@router.post("/verify-email", response_model=MeResponse)
def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    engine = _require_multi_user(request)
    _rate_gate(request, body.email)
    with Session(engine) as session:
        # BEGIN IMMEDIATE: two pending registrations may hold the same invite,
        # and only the first to verify may consume it.
        session.execute(text("BEGIN IMMEDIATE"))
        pending = _pending(session, body.email)
        if pending is None:
            _record_failure(request, body.email)
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        verdict = auth_codes.check_code(pending, body.code, settings)
        if verdict is not auth_codes.CodeVerdict.OK:
            if verdict is auth_codes.CodeVerdict.EXHAUSTED:
                session.delete(pending)
            session.commit()
            _record_failure(request, body.email)
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        invite = (
            session.execute(
                select(InviteCode).where(
                    InviteCode.code_hash == pending.invite_code_hash
                )
            )
            .scalars()
            .first()
        )
        if invite is None or invite.revoked_at is not None:
            raise ApiException(400, "INVITE_INVALID", "Unknown invitation code")
        if invite.used_at is not None:
            raise ApiException(400, "INVITE_USED", "Invitation code already used")
        now = datetime.now(timezone.utc)
        user = User(
            id=new_user_id(),
            username=pending.display_name or body.email.partition("@")[0],
            email=body.email,
            email_verified_at=now,
            password_hash=pending.password_hash,
            role="user",
        )
        session.add(user)
        invite.used_by = user.id
        invite.used_at = now
        session.delete(pending)
        session.commit()
        session.refresh(user)
        user_id, username, password_hash, epoch = (
            user.id,
            user.username,
            user.password_hash,
            user.session_epoch,
        )
    provision_workspace(
        request.app.state.data_dir,
        user_id,
        template_dir=request.app.state.template_config_dir,
    )
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings, user_id=user_id, password_hash=password_hash, epoch=epoch
        ),
    )
    return MeResponse(
        username=username,
        email=body.email,
        email_verified=True,
        role="user",
        auth_required=True,
    )


@router.post("/resend-code", status_code=202, response_model=CodeSentResponse)
def resend_code(
    body: ResendCodeRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    engine = _require_multi_user(request)
    if attempts.blocked(
        engine,
        email=body.email,
        ip=_client_ip(request),
        scopes=frozenset({"email_ip"}),
    ):
        raise ApiException(429, "RATE_LIMITED", "Too many requests; try again later")
    with Session(engine) as session:
        pending = _pending(session, body.email)
        if pending is None:
            return CodeSentResponse()  # unknown address reveals nothing
        code = auth_codes.generate_code()
        pending.code_hash = auth_codes.hash_code(code, settings)
        pending.expires_at = auth_codes.expires_at()
        pending.attempts = 0
        _send_or_fail(request, body.email, messages.verification_code(code))
        session.commit()
    # Each resend costs a unit of the email_ip budget, capping this at 3/hour
    # against the 10-per-15-minute budget without a dedicated counter.
    for _ in range(10 // _RESEND_LIMIT):
        _record_failure(request, body.email)
    return CodeSentResponse()
```

The resend cap reuses the `email_ip` budget rather than adding a fourth counter: each resend burns three units of a ten-unit budget, so the fourth call inside the window trips it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_verify_email.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api tests/api/test_auth_verify_email.py
git commit -m "Creates the account only on verified code, consuming the invite atomically"
```

---

### Task 11: Login by email, with the legacy username fallback

**Files:**

- Modify: `src/resume_agent/api/schemas/auth.py`
- Modify: `src/resume_agent/api/routers/auth.py` (`login`, `me`)
- Modify: `src/resume_agent/tenancy/bootstrap.py` (seed `AUTH_EMAIL`)
- Test: `tests/api/test_login_email.py`

**Interfaces:**

- Consumes: `attempts`, `auth`, `User`
- Produces:
  - `LoginRequest(identifier: str, password: str)` — the wire field is `identifier`
  - `MeResponse(username, email, email_verified, needs_email, google_linked, role, auth_required)`
  - `resolve_login_user(session, identifier) -> User | None` in `routers/auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_login_email.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password
from resume_agent.tenancy.system_db import User

PASSWORD = "quartz-lantern-42-drift"


def _add_user(app, email="ada@example.com", username="ada"):
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id="u9",
                username=username,
                email=email,
                email_verified_at=None,
                password_hash=hash_password(PASSWORD, iterations=1000),
                role="user",
            )
        )
        session.commit()


def _login(client, identifier, password=PASSWORD):
    return client.post(
        "/api/auth/login", json={"identifier": identifier, "password": password}
    )


def test_login_by_email(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        response = _login(client, "ada@example.com")
    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


def test_login_by_email_is_case_insensitive(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        assert _login(client, "Ada@Example.COM").status_code == 200


def test_a_legacy_account_without_email_logs_in_by_username(mu_app):
    with TestClient(mu_app) as client:
        response = _login(client, "owner", password="owner-password")
    assert response.status_code == 200
    assert response.json()["needsEmail"] is True


def test_an_account_with_an_email_cannot_log_in_by_username(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        response = _login(client, "ada")
    assert response.status_code == 401


def test_needs_email_is_false_once_an_email_exists(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        assert _login(client, "ada@example.com").json()["needsEmail"] is False


def test_me_reports_the_email_and_verification_state(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _login(client, "ada@example.com")
        body = client.get("/api/auth/me").json()
    assert body["email"] == "ada@example.com"
    assert body["emailVerified"] is False
    assert body["googleLinked"] is False


def test_a_passwordless_account_cannot_log_in_with_a_password(mu_app):
    with Session(mu_app.state.system_engine) as session:
        session.add(
            User(id="g1", username="g", email="g@example.com", password_hash="", role="user")
        )
        session.commit()
    with TestClient(mu_app) as client:
        response = _login(client, "g@example.com", password="")
    assert response.status_code in (401, 422)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_login_email.py -v`
Expected: FAIL — 422, `LoginRequest` has no `identifier` field.

- [ ] **Step 3: Update `api/schemas/auth.py`**

Replace `LoginRequest` with the following, and delete `RegisterRequest` from
this module — `schemas/auth_email.py` owns it now, so update any import.
`MeResponse` already gained its new fields in Task 10 and is left alone here:

```python
class LoginRequest(CamelModel):
    # Named `identifier`, not `email`: an account migrated from the pre-email
    # schema still signs in with its username until it adopts an address.
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().casefold()

```

- [ ] **Step 4: Update the `login` and `me` handlers**

In `api/routers/auth.py`, add the resolver and use it:

```python
def resolve_login_user(session: Session, identifier: str) -> User | None:
    """Email is the identifier; username works only for pre-email accounts.

    The `email IS NULL` clause is what keeps this from being a bypass: once an
    account adopts an address, its username stops resolving. Delete this
    fallback once every row has an email.
    """
    return (
        session.execute(
            select(User).where(
                (User.email == identifier)
                | ((User.email.is_(None)) & (User.username == identifier))
            )
        )
        .scalars()
        .first()
    )
```

Replace `body.username` with `body.identifier` throughout `login`, replace the `select(User).where(User.username == body.username)` lookup with `resolve_login_user(session, body.identifier)`, and build the response from the new fields:

```python
    return MeResponse(
        username=username,
        email=email,
        email_verified=email_verified_at is not None,
        needs_email=email is None,
        google_linked=google_sub is not None,
        role=cast(Literal["admin", "user"], role),
        auth_required=True,
    )
```

capturing `email`, `email_verified_at`, and `google_sub` in the same tuple unpack that already captures `user_id`, `username`, `role`, `password_hash`, and `epoch`.

Apply the same field expansion to the `me` handler's success branch.

- [ ] **Step 5: Seed the bootstrap admin's email**

In `tenancy/bootstrap.py`, in the `user_count == 0` branch, add `email=settings.auth_email or None` and `email_verified_at=utc_now() if settings.auth_email else None` to the `User(...)` construction, importing `utc_now` from `system_db`. The operator who set the env var owns the box, so the address is trusted without a code.

- [ ] **Step 6: Run tests and fix the fallout**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q`
Expected: the new file passes, and every existing test posting
`{"username": ...}` to `/api/auth/login` now 422s. Update each to
`{"identifier": ...}` — that is the expected contract change, not a
regression. Find them all rather than guessing:

Run: `grep -rln '"username":' tests/`

At minimum this covers `tests/api/test_account_password.py` (Task 5),
`tests/api/test_login_lockout.py` (Task 7), and any helper in
`tests/api/conftest.py`.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api src/resume_agent/tenancy/bootstrap.py tests/api
git commit -m "Makes email the login identifier with a username fallback for pre-email accounts"
```

---

### Task 12: Forgot and reset password

**Files:**

- Create: `src/resume_agent/api/routers/auth_password.py`
- Modify: `src/resume_agent/api/app.py` (mount, unguarded)
- Test: `tests/api/test_auth_password_reset.py`

**Interfaces:**

- Consumes: `auth_codes`, `validate_password`, `attempts`, `messages`, `PasswordResetCode`
- Produces: `POST /api/auth/password/forgot -> CodeSentResponse`, `POST /api/auth/password/reset -> MeResponse`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_password_reset.py`:

```python
import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password, verify_password
from resume_agent.tenancy.system_db import PasswordResetCode, User

OLD = "old-quartz-lantern-42"
NEW = "new-cobalt-meridian-77"
EMAIL = "ada@example.com"


def _add_user(app, *, password=OLD):
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id="u9",
                username="ada",
                email=EMAIL,
                password_hash=hash_password(password, iterations=1000) if password else "",
                role="user",
            )
        )
        session.commit()


def _last_code(app):
    return re.search(r"\b(\d{6})\b", app.state.mailer.sent[-1][2]).group(1)


def _forgot(client, email=EMAIL):
    return client.post("/api/auth/password/forgot", json={"email": email})


def _reset(client, code, new=NEW, email=EMAIL):
    return client.post(
        "/api/auth/password/reset",
        json={"email": email, "code": code, "newPassword": new},
    )


def test_forgot_returns_202_for_a_known_address_and_mails_a_code(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        response = _forgot(client)
    assert response.status_code == 202
    assert response.json() == {"status": "sent"}
    assert len(mu_app.state.mailer.sent) == 1


def test_forgot_is_indistinguishable_for_an_unknown_address(mu_app):
    with TestClient(mu_app) as client:
        known_body = None
        _add_user(mu_app)
        known = _forgot(client)
        known_body = known.json()
    with TestClient(mu_app) as client:
        unknown = _forgot(client, "ghost@example.com")
    assert (unknown.status_code, unknown.json()) == (known.status_code, known_body)


def test_forgot_never_returns_the_code(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        response = _forgot(client)
    assert _last_code(mu_app) not in response.text


def test_reset_rotates_the_hash_bumps_the_epoch_and_signs_in(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _forgot(client)
        response = _reset(client, _last_code(mu_app))
        assert response.status_code == 200
        assert client.get("/api/auth/me").json()["email"] == EMAIL
    with Session(mu_app.state.system_engine) as session:
        user = session.get(User, "u9")
        assert verify_password(NEW, user.password_hash)
        assert user.session_epoch == 1


def test_reset_consumes_the_code(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _forgot(client)
        code = _last_code(mu_app)
        _reset(client, code)
        replay = _reset(client, code, new="third-tungsten-vector-91")
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "CODE_INVALID"


def test_reset_rejects_a_weak_new_password(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _forgot(client)
        response = _reset(client, _last_code(mu_app), new="passwordpassword")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_WEAK"


def test_reset_rejects_reusing_the_current_password(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _forgot(client)
        response = _reset(client, _last_code(mu_app), new=OLD)
    assert response.status_code == 400
    assert "different" in response.json()["error"]["message"].lower()


def test_reset_sends_a_password_changed_notice(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _forgot(client)
        _reset(client, _last_code(mu_app))
    subjects = [subject for _to, subject, _body in mu_app.state.mailer.sent]
    assert any("password was changed" in subject for subject in subjects)


def test_reset_sets_a_password_on_a_passwordless_google_account(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app, password=None)
        _forgot(client)
        assert _reset(client, _last_code(mu_app)).status_code == 200
    with Session(mu_app.state.system_engine) as session:
        assert verify_password(NEW, session.get(User, "u9").password_hash)


def test_a_stale_session_dies_after_a_reset(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        client.post("/api/auth/login", json={"identifier": EMAIL, "password": OLD})
        stale = client.cookies.get("ra_session")
    with TestClient(mu_app) as other:
        _forgot(other)
        _reset(other, _last_code(mu_app))
    with TestClient(mu_app) as third:
        third.cookies.set("ra_session", stale)
        assert third.get("/api/auth/me").json().get("username") is None


def test_five_wrong_codes_exhaust_the_reset(mu_app):
    with TestClient(mu_app) as client:
        _add_user(mu_app)
        _forgot(client)
        code = _last_code(mu_app)
        for _ in range(5):
            _reset(client, "000000")
        response = _reset(client, code)
    assert response.status_code == 400
    with Session(mu_app.state.system_engine) as session:
        assert session.execute(select(PasswordResetCode)).first() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_password_reset.py -v`
Expected: FAIL — 404 for both routes.

- [ ] **Step 3: Write `api/routers/auth_password.py`**

```python
"""Password recovery by emailed single-use code.

No credential is ever emailed. Rotating the hash and bumping the epoch both
feed the session HMAC key, so a reset revokes every outstanding cookie with no
session table to sweep.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from resume_agent.api import attempts, auth, auth_codes
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.password_policy import validate_password
from resume_agent.api.routers.auth_register import (
    _client_ip,
    _record_failure,
    _require_multi_user,
    _send_or_fail,
)
from resume_agent.api.schemas.auth import MeResponse
from resume_agent.api.schemas.auth_email import (
    CodeSentResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.tenancy.system_db import PasswordResetCode, User

router = APIRouter(prefix="/auth/password", tags=["auth"])


def _rate_gate(request: Request, email: str) -> None:
    engine = _require_multi_user(request)
    if attempts.blocked(engine, email=email, ip=_client_ip(request)):
        raise ApiException(429, "RATE_LIMITED", "Too many attempts; try again later")


@router.post("/forgot", status_code=202, response_model=CodeSentResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    engine = _require_multi_user(request)
    _rate_gate(request, body.email)
    with Session(engine) as session:
        user = (
            session.execute(select(User).where(User.email == body.email))
            .scalars()
            .first()
        )
        if user is None or user.disabled_at is not None:
            # Identical status and body to the success path.
            return CodeSentResponse()
        code = auth_codes.generate_code()
        session.execute(
            delete(PasswordResetCode).where(PasswordResetCode.user_id == user.id)
        )
        session.add(
            PasswordResetCode(
                id=uuid.uuid4().hex[:12],
                user_id=user.id,
                code_hash=auth_codes.hash_code(code, settings),
                expires_at=auth_codes.expires_at(),
            )
        )
        session.flush()
        _send_or_fail(request, body.email, messages.reset_code(code))
        session.commit()
    return CodeSentResponse()


@router.post("/reset", response_model=MeResponse)
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    engine = _require_multi_user(request)
    _rate_gate(request, body.email)
    with Session(engine) as session:
        user = (
            session.execute(select(User).where(User.email == body.email))
            .scalars()
            .first()
        )
        row = (
            None
            if user is None
            else session.execute(
                select(PasswordResetCode).where(
                    PasswordResetCode.user_id == user.id,
                    PasswordResetCode.consumed_at.is_(None),
                    # An adoption code (pending_email set) must never be
                    # spendable as a password reset.
                    PasswordResetCode.pending_email.is_(None),
                )
            )
            .scalars()
            .first()
        )
        if user is None or row is None:
            _record_failure(request, body.email)
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        verdict = auth_codes.check_code(row, body.code, settings)
        if verdict is not auth_codes.CodeVerdict.OK:
            if verdict is auth_codes.CodeVerdict.EXHAUSTED:
                session.delete(row)
            session.commit()
            _record_failure(request, body.email)
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        validate_password(
            body.new_password,
            email=body.email,
            display_name=user.username,
            checker=request.app.state.breach_checker,
        )
        if user.password_hash and auth.verify_password(
            body.new_password, user.password_hash
        ):
            raise ApiException(
                400, "PASSWORD_WEAK", "Choose a password different from your current one"
            )
        user.password_hash = auth.hash_password(body.new_password)
        user.session_epoch += 1
        attempts.clear_lockout(user)
        row.consumed_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(user)
        user_id, username, password_hash, epoch, verified, google_sub = (
            user.id,
            user.username,
            user.password_hash,
            user.session_epoch,
            user.email_verified_at,
            user.google_sub,
        )
    attempts.reset(engine, email=body.email, ip=_client_ip(request))
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings, user_id=user_id, password_hash=password_hash, epoch=epoch
        ),
    )
    notice = messages.password_changed(settings.app_base_url)
    request.app.state.mailer.notify(
        to=body.email, subject=notice.subject, body=notice.body
    )
    return MeResponse(
        username=username,
        email=body.email,
        email_verified=verified is not None,
        google_linked=google_sub is not None,
        auth_required=True,
    )
```

Importing the four underscore-prefixed helpers from `auth_register` is deliberate: they are package-internal shared plumbing, and duplicating them would let the two routers' rate-limiting drift apart.

- [ ] **Step 4: Mount the router**

In `api/app.py`, beside the other unguarded auth routers:

```python
    app.include_router(auth_password_router.router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_password_reset.py -v && ruff check src/resume_agent/api`
Expected: 11 passed, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api tests/api/test_auth_password_reset.py
git commit -m "Adds password recovery by emailed single-use code with full session revocation"
```

---

### Task 13: Account email adoption, revoke-all, and health

**Files:**

- Modify: `src/resume_agent/api/routers/account.py`
- Modify: `src/resume_agent/api/schemas/account.py`
- Modify: `src/resume_agent/api/routers/health.py`
- Create: `src/resume_agent/api/schemas/health.py`
- Test: `tests/api/test_account_email.py`, `tests/api/test_health.py`

**Interfaces:**

- Produces:
  - `POST /api/account/email` — `{ email }` → `CodeSentResponse`
  - `POST /api/account/email/verify` — `{ email, code }` → `MeResponse`
  - `POST /api/account/sessions/revoke-all` → `{ "status": "ok" }`
  - `HealthOut(status: str, mail_configured: bool)`
  - `SetEmailRequest(email: EmailStr)`, `VerifyAccountEmailRequest(email: EmailStr, code: str)`

**Where the adoption code lives.** Email adoption needs a code bound to an
existing user, which is exactly what `PasswordResetCode` already is — a row
keyed on `user_id` meaning "a code this account must present". It gains one
nullable `pending_email` column: set, the row is an adoption; `NULL`, it is an
ordinary reset. `PendingRegistration` is the wrong home (it carries an invite
and a password an adoption has no use for) and a third table would duplicate
the TTL and attempt logic for a third time. The column and its migration
already landed in Task 2, and Task 12's reset query already excludes rows that
have it set — so this task only reads and writes it.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_account_email.py`:

```python
import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import User


def _login_legacy(client):
    return client.post(
        "/api/auth/login", json={"identifier": "owner", "password": "owner-password"}
    )


def _last_code(app):
    return re.search(r"\b(\d{6})\b", app.state.mailer.sent[-1][2]).group(1)


def test_a_legacy_account_can_adopt_and_verify_an_email(mu_app):
    with TestClient(mu_app) as client:
        assert _login_legacy(client).json()["needsEmail"] is True
        assert (
            client.post(
                "/api/account/email", json={"email": "owner@example.com"}
            ).status_code
            == 202
        )
        response = client.post(
            "/api/account/email/verify",
            json={"email": "owner@example.com", "code": _last_code(mu_app)},
        )
        assert response.status_code == 200
        assert response.json()["needsEmail"] is False
        assert client.get("/api/auth/me").json()["emailVerified"] is True


def test_after_adoption_the_username_no_longer_logs_in(mu_app):
    with TestClient(mu_app) as client:
        _login_legacy(client)
        client.post("/api/account/email", json={"email": "owner@example.com"})
        client.post(
            "/api/account/email/verify",
            json={"email": "owner@example.com", "code": _last_code(mu_app)},
        )
    with TestClient(mu_app) as other:
        assert _login_legacy(other).status_code == 401
        assert (
            other.post(
                "/api/auth/login",
                json={"identifier": "owner@example.com", "password": "owner-password"},
            ).status_code
            == 200
        )


def test_adopting_an_address_another_account_owns_is_refused(mu_app):
    with TestClient(mu_app) as client:
        with Session(mu_app.state.system_engine) as session:
            session.add(
                User(id="u9", username="ada", email="taken@example.com",
                     password_hash="x", role="user")
            )
            session.commit()
        _login_legacy(client)
        response = client.post("/api/account/email", json={"email": "taken@example.com"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_a_wrong_adoption_code_is_rejected(mu_app):
    with TestClient(mu_app) as client:
        _login_legacy(client)
        client.post("/api/account/email", json={"email": "owner@example.com"})
        response = client.post(
            "/api/account/email/verify",
            json={"email": "owner@example.com", "code": "000000"},
        )
    assert response.status_code == 400


def test_revoke_all_kills_other_sessions_but_keeps_the_caller(mu_app):
    with TestClient(mu_app) as first:
        _login_legacy(first)
        stale = first.cookies.get("ra_session")
    with TestClient(mu_app) as second:
        _login_legacy(second)
        assert second.post("/api/account/sessions/revoke-all").status_code == 200
        assert second.get("/api/auth/me").json()["username"] == "owner"
    with TestClient(mu_app) as third:
        third.cookies.set("ra_session", stale)
        assert third.get("/api/auth/me").json().get("username") is None
```

Create `tests/api/test_health.py`:

```python
from fastapi.testclient import TestClient


def test_health_reports_mail_unconfigured_by_default(mu_app):
    with TestClient(mu_app) as client:
        body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["mailConfigured"] is False


def test_health_reports_mail_configured_when_smtp_host_is_set(mu_app, monkeypatch):
    mu_app.state.settings = mu_app.state.settings.model_copy(
        update={"smtp_host": "smtp.example.com"}
    )
    with TestClient(mu_app) as client:
        assert client.get("/api/health").json()["mailConfigured"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account_email.py tests/api/test_health.py -v`
Expected: FAIL — 404 on the account routes, `KeyError: 'mailConfigured'` on health.

- [ ] **Step 3: Confirm the `pending_email` column is present**

Task 2 already added `PasswordResetCode.pending_email` and its migration, and
Task 12's reset query already filters it out. Verify before building on it:

Run: `.venv/Scripts/python.exe -c "from resume_agent.tenancy.system_db import PasswordResetCode; print(PasswordResetCode.pending_email)"`
Expected: prints the column, no AttributeError.

- [ ] **Step 4: Add the schemas**

To `api/schemas/account.py`:

```python
class SetEmailRequest(CamelModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class VerifyAccountEmailRequest(SetEmailRequest):
    code: str = Field(pattern=r"^\d{6}$")
```

Create `api/schemas/health.py`:

```python
from resume_agent.api.schemas.base import CamelModel


class HealthOut(CamelModel):
    status: str = "ok"
    mail_configured: bool = False
```

- [ ] **Step 5: Add the account handlers**

Append to `api/routers/account.py`:

```python
@router.post("/email", status_code=202, response_model=CodeSentResponse)
def set_email(
    body: SetEmailRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        owner = (
            session.execute(select(User).where(User.email == body.email))
            .scalars()
            .first()
        )
        if owner is not None and owner.id != context.user_id:
            raise ApiException(409, "EMAIL_TAKEN", "That address is already in use")
        code = auth_codes.generate_code()
        session.execute(
            delete(PasswordResetCode).where(
                PasswordResetCode.user_id == context.user_id
            )
        )
        session.add(
            PasswordResetCode(
                id=uuid.uuid4().hex[:12],
                user_id=context.user_id,
                code_hash=auth_codes.hash_code(code, settings),
                expires_at=auth_codes.expires_at(),
                pending_email=body.email,
            )
        )
        session.flush()
        message = messages.verification_code(code)
        try:
            request.app.state.mailer.send(
                to=body.email, subject=message.subject, body=message.body
            )
        except MailDeliveryError as error:
            raise ApiException(
                503, "MAIL_UNAVAILABLE", "Could not send the verification email"
            ) from error
        session.commit()
    return CodeSentResponse()


@router.post("/email/verify", response_model=MeResponse)
def verify_account_email(
    body: VerifyAccountEmailRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        row = (
            session.execute(
                select(PasswordResetCode).where(
                    PasswordResetCode.user_id == context.user_id,
                    PasswordResetCode.pending_email == body.email,
                    PasswordResetCode.consumed_at.is_(None),
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        verdict = auth_codes.check_code(row, body.code, settings)
        if verdict is not auth_codes.CodeVerdict.OK:
            if verdict is auth_codes.CodeVerdict.EXHAUSTED:
                session.delete(row)
            session.commit()
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        user = session.get(User, context.user_id)
        assert user is not None
        now = datetime.now(timezone.utc)
        user.email = body.email
        user.email_verified_at = now
        row.consumed_at = now
        session.commit()
        session.refresh(user)
        return MeResponse(
            username=user.username,
            email=user.email,
            email_verified=True,
            needs_email=False,
            google_linked=user.google_sub is not None,
            role=cast(Literal["admin", "user"], user.role),
            auth_required=True,
        )


@router.post("/sessions/revoke-all")
def revoke_all_sessions(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, context.user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such account")
        user.session_epoch += 1
        session.commit()
        session.refresh(user)
        password_hash, epoch = user.password_hash, user.session_epoch
    # Re-issue the caller's own cookie: "everywhere else", not "everywhere".
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings, user_id=context.user_id, password_hash=password_hash, epoch=epoch
        ),
    )
    return {"status": "ok"}
```

Add the needed imports to `account.py`: `uuid` (already present), `delete` from `sqlalchemy`, `cast`/`Literal` from `typing`, `auth_codes`, `CodeSentResponse`, `MeResponse`, `SetEmailRequest`, `VerifyAccountEmailRequest`, `PasswordResetCode`, `MailDeliveryError`, and `messages`.

- [ ] **Step 6: Update health**

Replace `api/routers/health.py`:

```python
from fastapi import APIRouter, Request

from resume_agent.api.schemas.health import HealthOut
from resume_agent.mail.mailer import mail_configured

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    # mailConfigured is the guard against a production box silently logging
    # live verification codes through NullMailer.
    return HealthOut(status="ok", mail_configured=mail_configured(request.app.state.settings))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q && ruff check src/resume_agent`
Expected: all pass.

- [ ] **Step 8: Regenerate the API contract**

Run: `bash scripts/gen_ts_client.sh && .venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS. `contracts/openapi.json` and `contracts/ts/api.ts` both change — this is the breaking contract change the spec calls out.

- [ ] **Step 9: Commit**

```bash
git add src/resume_agent tests/api contracts
git commit -m "Adds account email adoption, sign-out-everywhere, and mailConfigured on health"
```

---

**Phase 4 checkpoint.** Run `.venv/Scripts/python.exe -m pytest -q` and `ruff check`. The whole email flow works end to end through the API; the web app still posts `username` and is broken until Phase 6.

---

## Phase 5 — Google sign-in

### Task 14: OAuth state signing

**Files:**

- Modify: `src/resume_agent/api/auth.py` (append)
- Test: `tests/api/test_oauth_state.py`

**Interfaces:**

- Consumes: `Settings.session_secret`, `_sign_user`
- Produces:
  - `OAUTH_STATE_TTL_SECONDS = 600`
  - `OAuthState(mode: str, invite_hash: str)` frozen dataclass
  - `issue_oauth_state(settings, *, mode: str, invite_hash: str = "", now: float | None = None) -> str`
  - `verify_oauth_state(state: str, settings, *, now: float | None = None) -> OAuthState | None`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_oauth_state.py`:

```python
from resume_agent.api import auth
from resume_agent.config import Settings

SETTINGS = Settings(_env_file=None, session_secret="s3cret")


def test_round_trips_mode_and_invite_hash():
    state = auth.issue_oauth_state(SETTINGS, mode="register", invite_hash="abc123")
    parsed = auth.verify_oauth_state(state, SETTINGS)
    assert parsed is not None
    assert (parsed.mode, parsed.invite_hash) == ("register", "abc123")


def test_login_mode_carries_no_invite():
    state = auth.issue_oauth_state(SETTINGS, mode="login")
    parsed = auth.verify_oauth_state(state, SETTINGS)
    assert parsed is not None
    assert parsed.invite_hash == ""


def test_a_tampered_invite_hash_is_rejected():
    state = auth.issue_oauth_state(SETTINGS, mode="register", invite_hash="abc123")
    mode, invite, nonce, expiry, signature = state.split(":")
    forged = f"{mode}:deadbeef:{nonce}:{expiry}:{signature}"
    assert auth.verify_oauth_state(forged, SETTINGS) is None


def test_a_tampered_mode_is_rejected():
    state = auth.issue_oauth_state(SETTINGS, mode="login")
    mode, invite, nonce, expiry, signature = state.split(":")
    assert auth.verify_oauth_state(f"register:{invite}:{nonce}:{expiry}:{signature}", SETTINGS) is None


def test_an_expired_state_is_rejected():
    state = auth.issue_oauth_state(SETTINGS, mode="login", now=0.0)
    assert auth.verify_oauth_state(state, SETTINGS, now=auth.OAUTH_STATE_TTL_SECONDS + 1) is None


def test_a_state_from_a_different_secret_is_rejected():
    other = Settings(_env_file=None, session_secret="different")
    assert auth.verify_oauth_state(auth.issue_oauth_state(other, mode="login"), SETTINGS) is None


def test_no_secret_configured_verifies_nothing():
    blank = Settings(_env_file=None, session_secret="")
    assert auth.verify_oauth_state("anything:x:y:1:z", blank) is None


def test_two_states_differ_by_nonce():
    first = auth.issue_oauth_state(SETTINGS, mode="login", now=1000.0)
    second = auth.issue_oauth_state(SETTINGS, mode="login", now=1000.0)
    assert first != second


def test_garbage_is_rejected_without_raising():
    for value in ("", "abc", "a:b:c", "a:b:c:notanint:e"):
        assert auth.verify_oauth_state(value, SETTINGS) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_oauth_state.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'issue_oauth_state'`

- [ ] **Step 3: Append to `api/auth.py`**

```python
OAUTH_STATE_TTL_SECONDS = 600


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
    """Sign the pre-account OAuth state.

    issue_link_token cannot be reused: it is keyed on a user_id that does not
    exist yet during signup. The invite rides inside the signature so it
    cannot be swapped between the start call and the callback.
    """
    expiry = int((time.time() if now is None else now) + OAUTH_STATE_TTL_SECONDS)
    nonce = secrets.token_urlsafe(12)
    payload = f"{mode}:{invite_hash}:{nonce}:{expiry}"
    return f"{payload}:{_sign_user(settings, payload, '', namespace='oauth')}"


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
    payload = f"{mode}:{invite_hash}:{nonce}:{expiry}"
    expected = _sign_user(settings, payload, "", namespace="oauth")
    if not hmac.compare_digest(signature, expected):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return OAuthState(mode=mode, invite_hash=invite_hash)
```

Add `from dataclasses import dataclass` to the imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_oauth_state.py -v && ruff check src/resume_agent/api/auth.py`
Expected: 9 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/auth.py tests/api/test_oauth_state.py
git commit -m "Adds signed pre-account OAuth state carrying mode and invite"
```

---

### Task 15: Google start and callback

**Files:**

- Create: `src/resume_agent/api/routers/auth_google.py`
- Create: `src/resume_agent/api/schemas/auth_google.py`
- Modify: `src/resume_agent/api/app.py` (mount both routers unguarded)
- Test: `tests/api/test_auth_google.py`

**Interfaces:**

- Consumes: `auth.issue_oauth_state`, `auth.verify_oauth_state`, `auth.set_session_cookie`, `attempts.IP_ONLY`, `InviteCode`, `User`, `provision_workspace`, `messages.google_linked`
- Produces:
  - `GET /api/auth/google/start?mode=&invite=` → `GoogleStartOut(auth_url: str)`
  - `GET /api/auth/google/callback` → `RedirectResponse`
  - `GOOGLE_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]`
  - `_verify_id_token(flow, settings) -> dict` — the single seam tests monkeypatch

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_google.py`:

```python
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.routers import auth_google
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, User

CLIENT = {"google_oauth_client_id": "cid", "google_oauth_client_secret": "csecret"}


def _configure(app):
    app.state.settings = app.state.settings.model_copy(update=CLIENT)


def _mint_invite(app, code="inv_googletest1"):
    with Session(app.state.system_engine) as session:
        session.add(
            InviteCode(
                id="i1",
                code_hash=hash_secret(code),
                created_by="u1",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
        session.commit()
    return code


def _fake_google(monkeypatch, claims):
    """Replace the two network seams: token exchange and id_token verification."""

    class FakeCredentials:
        id_token = "fake"

    class FakeFlow:
        credentials = FakeCredentials()

        def authorization_url(self, **kwargs):
            return ("https://accounts.google.com/o/oauth2/auth?fake=1", kwargs.get("state"))

        def fetch_token(self, code=""):
            return None

    monkeypatch.setattr(auth_google, "_build_flow", lambda *a, **k: FakeFlow())
    monkeypatch.setattr(auth_google, "_verify_id_token", lambda flow, settings: claims)


def _start(client, mode="login", invite=None):
    params = {"mode": mode}
    if invite:
        params["invite"] = invite
    return client.get("/api/auth/google/start", params=params)


def _state_from(client, **kwargs):
    return _start(client, **kwargs).json()["authUrl"], client


def test_start_requires_a_configured_client(mu_app):
    with TestClient(mu_app) as client:
        response = _start(client)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GMAIL_CLIENT_MISSING"


def test_start_returns_an_auth_url(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {})
    with TestClient(mu_app) as client:
        response = _start(client)
    assert response.status_code == 200
    assert response.json()["authUrl"].startswith("https://accounts.google.com/")


def test_callback_signs_in_a_matching_google_sub(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-123", "email": "ada@example.com", "email_verified": True})
    with Session(mu_app.state.system_engine) as session:
        session.add(
            User(id="u9", username="ada", email="ada@example.com",
                 google_sub="g-123", password_hash="", role="user")
        )
        session.commit()
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        # The state is minted directly rather than parsed out of the fake
        # authorization URL — the callback is what is under test here.
        signed = auth_module.issue_oauth_state(mu_app.state.settings, mode="login")
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": signed},
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert response.headers["location"] == "/"
        assert client.get("/api/auth/me").json()["email"] == "ada@example.com"


def test_callback_links_an_existing_account_when_google_verified_the_email(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-new", "email": "ada@example.com", "email_verified": True})
    with Session(mu_app.state.system_engine) as session:
        session.add(
            User(id="u9", username="ada", email="ada@example.com",
                 password_hash="x", role="user")
        )
        session.commit()
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        signed = auth_module.issue_oauth_state(mu_app.state.settings, mode="login")
        client.get("/api/auth/google/callback", params={"code": "x", "state": signed},
                   follow_redirects=False)
    with Session(mu_app.state.system_engine) as session:
        assert session.get(User, "u9").google_sub == "g-new"
    subjects = [subject for _to, subject, _body in mu_app.state.mailer.sent]
    assert any("Google account was linked" in subject for subject in subjects)


def test_callback_refuses_to_link_when_google_did_not_verify_the_email(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-evil", "email": "ada@example.com", "email_verified": False})
    with Session(mu_app.state.system_engine) as session:
        session.add(
            User(id="u9", username="ada", email="ada@example.com",
                 password_hash="x", role="user")
        )
        session.commit()
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        signed = auth_module.issue_oauth_state(mu_app.state.settings, mode="login")
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": signed},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?error=unverified_google"
    with Session(mu_app.state.system_engine) as session:
        assert session.get(User, "u9").google_sub is None


def test_callback_registers_a_new_account_with_a_valid_invite(mu_app, monkeypatch):
    _configure(mu_app)
    invite = _mint_invite(mu_app)
    _fake_google(monkeypatch, {"sub": "g-1", "email": "new@example.com", "email_verified": True})
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        signed = auth_module.issue_oauth_state(
            mu_app.state.settings, mode="register", invite_hash=hash_secret(invite)
        )
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": signed},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/"
    with Session(mu_app.state.system_engine) as session:
        user = session.execute(
            select(User).where(User.email == "new@example.com")
        ).scalars().one()
        assert user.email_verified_at is not None
        assert user.password_hash == ""
        assert session.get(InviteCode, "i1").used_by == user.id
    assert (mu_app.state.data_dir / "users" / user.id).is_dir()


def test_callback_rejects_register_without_a_valid_invite(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-1", "email": "new@example.com", "email_verified": True})
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        signed = auth_module.issue_oauth_state(
            mu_app.state.settings, mode="register", invite_hash="not-a-real-hash"
        )
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": signed},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/register?error=invite_invalid"


def test_callback_on_login_mode_with_no_account_redirects(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-1", "email": "ghost@example.com", "email_verified": True})
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        signed = auth_module.issue_oauth_state(mu_app.state.settings, mode="login")
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": signed},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?error=no_account"


def test_callback_rejects_a_forged_state(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-1", "email": "a@example.com", "email_verified": True})
    with TestClient(mu_app) as client:
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": "forged:x:y:9999999999:z"},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?error=invalid_state"


def test_callback_on_user_denial_redirects_without_touching_google(mu_app):
    with TestClient(mu_app) as client:
        response = client.get(
            "/api/auth/google/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?error=denied"


def test_a_disabled_account_cannot_sign_in_with_google(mu_app, monkeypatch):
    _configure(mu_app)
    _fake_google(monkeypatch, {"sub": "g-123", "email": "ada@example.com", "email_verified": True})
    with Session(mu_app.state.system_engine) as session:
        session.add(
            User(id="u9", username="ada", email="ada@example.com", google_sub="g-123",
                 password_hash="", role="user",
                 disabled_at=datetime.now(timezone.utc))
        )
        session.commit()
    from resume_agent.api import auth as auth_module

    with TestClient(mu_app) as client:
        signed = auth_module.issue_oauth_state(mu_app.state.settings, mode="login")
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "x", "state": signed},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/login?error=disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_google.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.api.routers.auth_google'`

- [ ] **Step 3: Write `api/schemas/auth_google.py`**

```python
from resume_agent.api.schemas.base import CamelModel


class GoogleStartOut(CamelModel):
    auth_url: str
```

- [ ] **Step 4: Write `api/routers/auth_google.py`**

```python
"""Sign in with Google.

Scopes are identity-only (openid/email/profile) — a stranger evaluating the
product is never asked for inbox access. Gmail sync stays its own opt-in in
Settings, pre-warmed by login_hint + incremental authorization.

The callback is unguarded and authenticates via the signed `state`, because
Google's top-level redirect does not carry SameSite cookies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from resume_agent.api import attempts, auth as auth_module
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth_google import GoogleStartOut
from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, User
from resume_agent.tenancy.workspace import provision_workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["auth"])
callback_router = APIRouter(prefix="/auth/google", tags=["auth"])

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_client(settings: Settings) -> None:
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        raise ApiException(
            409,
            "GMAIL_CLIENT_MISSING",
            "No Google OAuth client configured. Set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET.",
        )


def _redirect_uri(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{proto}://{host}/api/auth/google/callback"


def _build_flow(settings: Settings, redirect_uri: str) -> Any:
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    # PKCE off for the same reason as the Gmail flow: start and callback build
    # independent Flow objects, so a generated verifier cannot survive to the
    # exchange. This is a confidential client; the secret authenticates it.
    return Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def _verify_id_token(flow: Any, settings: Settings) -> dict:
    """Claims are never read unverified — the single network seam tests fake."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(
        flow.credentials.id_token,
        google_requests.Request(),
        settings.google_oauth_client_id,
    )


@router.get("/start", response_model=GoogleStartOut)
def google_start(
    request: Request,
    mode: str = Query(default="login", pattern="^(login|register)$"),
    invite: str = Query(default=""),
) -> GoogleStartOut:
    settings = get_settings_dep(request)
    _require_client(settings)
    engine = getattr(request.app.state, "system_engine", None)
    if engine is not None and attempts.blocked(
        engine, email="", ip=_client_ip(request), scopes=attempts.IP_ONLY
    ):
        raise ApiException(429, "RATE_LIMITED", "Too many attempts; try again later")
    # The IP gate lives on `start`, not on the callback: a callback can only
    # be reached with a signed state that `start` minted, so gating here
    # bounds the whole flow without risking a redirect that returns JSON.
    state = auth_module.issue_oauth_state(
        settings, mode=mode, invite_hash=hash_secret(invite) if invite else ""
    )
    flow = _build_flow(settings, _redirect_uri(request))
    url, _state = flow.authorization_url(
        access_type="offline", prompt="consent", state=state
    )
    return GoogleStartOut(auth_url=url)


def _finish(target: str) -> RedirectResponse:
    return RedirectResponse(target)


def _sign_in(request: Request, settings: Settings, user: User) -> RedirectResponse:
    response = _finish("/")
    auth_module.set_session_cookie(
        request,
        response,
        auth_module.issue_user_session(
            settings,
            user_id=user.id,
            password_hash=user.password_hash,
            epoch=user.session_epoch,
        ),
    )
    return response


@callback_router.get("/callback", include_in_schema=False)
def google_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
):
    if error:
        return _finish("/login?error=denied")
    settings = request.app.state.settings
    parsed = auth_module.verify_oauth_state(state, settings)
    if parsed is None:
        return _finish("/login?error=invalid_state")
    engine = getattr(request.app.state, "system_engine", None)
    if engine is None:
        return _finish("/login?error=unavailable")
    try:
        _require_client(settings)
        flow = _build_flow(settings, _redirect_uri(request))
        flow.fetch_token(code=code)
        claims = _verify_id_token(flow, settings)
    except ApiException:
        logger.exception("Google callback rejected (client config)")
        return _finish("/login?error=unavailable")
    except Exception:  # noqa: BLE001 — never render a raw OAuth error page
        logger.exception("Google callback token exchange failed")
        return _finish("/login?error=exchange_failed")

    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().casefold()
    verified = bool(claims.get("email_verified"))
    if not subject or not email:
        return _finish("/login?error=exchange_failed")

    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        by_sub = (
            session.execute(select(User).where(User.google_sub == subject))
            .scalars()
            .first()
        )
        if by_sub is not None:
            if by_sub.disabled_at is not None:
                return _finish("/login?error=disabled")
            by_sub.last_active_at = now
            session.commit()
            session.refresh(by_sub)
            return _sign_in(request, settings, by_sub)

        by_email = (
            session.execute(select(User).where(User.email == email)).scalars().first()
        )
        if by_email is not None:
            # Matching an OAuth identity on email alone is an account-takeover
            # vector: an attacker registers the victim's address at a provider
            # that never verified it. Require Google's own assertion, then pin
            # to `sub` from here on.
            if not verified:
                return _finish("/login?error=unverified_google")
            if by_email.disabled_at is not None:
                return _finish("/login?error=disabled")
            by_email.google_sub = subject
            by_email.last_active_at = now
            session.commit()
            session.refresh(by_email)
            notice = messages.google_linked(settings.app_base_url)
            request.app.state.mailer.notify(
                to=email, subject=notice.subject, body=notice.body
            )
            return _sign_in(request, settings, by_email)

        if parsed.mode != "register":
            return _finish("/login?error=no_account")
        if not verified:
            return _finish("/register?error=unverified_google")
        invite = (
            session.execute(
                select(InviteCode).where(InviteCode.code_hash == parsed.invite_hash)
            )
            .scalars()
            .first()
            if parsed.invite_hash
            else None
        )
        invite_expires = None if invite is None else invite.expires_at
        if invite_expires is not None and invite_expires.tzinfo is None:
            invite_expires = invite_expires.replace(tzinfo=timezone.utc)
        if (
            invite is None
            or invite.revoked_at is not None
            or invite.used_at is not None
            or invite_expires is None
            or invite_expires <= now
        ):
            return _finish("/register?error=invite_invalid")
        user = User(
            id=new_user_id(),
            username=str(claims.get("name") or email.partition("@")[0])[:64],
            email=email,
            email_verified_at=now,  # Google already verified it
            google_sub=subject,
            password_hash="",  # no password; recovery is an ordinary reset
            role="user",
            last_active_at=now,
        )
        session.add(user)
        invite.used_by = user.id
        invite.used_at = now
        session.commit()
        session.refresh(user)
        user_id = user.id
        provision_workspace(
            request.app.state.data_dir,
            user_id,
            template_dir=request.app.state.template_config_dir,
        )
        return _sign_in(request, settings, user)
```

- [ ] **Step 5: Mount both routers**

In `api/app.py`, beside the other unguarded auth routers:

```python
    app.include_router(auth_google_router.router, prefix="/api")
    app.include_router(auth_google_router.callback_router, prefix="/api")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_google.py -v && ruff check src/resume_agent/api`
Expected: 11 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api tests/api/test_auth_google.py
git commit -m "Adds Google sign-in pinned to sub and refusing unverified email links"
```

---

### Task 16: Gmail pre-wiring and unlink

**Files:**

- Modify: `src/resume_agent/api/routers/gmail.py` (`gmail_connect`)
- Modify: `src/resume_agent/api/routers/account.py` (append `DELETE /google`)
- Test: `tests/api/test_gmail_prewire.py`

**Interfaces:**

- Produces: `DELETE /api/account/google -> MeResponse`; `gmail_connect` now passes `login_hint` and `include_granted_scopes`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_gmail_prewire.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resume_agent.api.routers import gmail as gmail_router
from resume_agent.tenancy.system_db import User


def _configure(app):
    app.state.settings = app.state.settings.model_copy(
        update={"google_oauth_client_id": "cid", "google_oauth_client_secret": "cs"}
    )


def _capture_flow(monkeypatch):
    captured: dict = {}

    class FakeFlow:
        def authorization_url(self, **kwargs):
            captured.update(kwargs)
            return ("https://accounts.google.com/o/oauth2/auth", kwargs.get("state"))

    monkeypatch.setattr(gmail_router, "_build_flow", lambda *a, **k: FakeFlow())
    return captured


def _login(client):
    return client.post(
        "/api/auth/login", json={"identifier": "owner", "password": "owner-password"}
    )


def test_connect_passes_login_hint_and_incremental_auth(mu_app, monkeypatch):
    _configure(mu_app)
    captured = _capture_flow(monkeypatch)
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter(User.username == "owner").one()
        user.email = "owner@example.com"
        session.commit()
    with TestClient(mu_app) as client:
        _login(client)
        assert client.get("/api/gmail/connect").status_code == 200
    assert captured["login_hint"] == "owner@example.com"
    assert captured["include_granted_scopes"] == "true"


def test_connect_omits_login_hint_when_the_account_has_no_email(mu_app, monkeypatch):
    _configure(mu_app)
    captured = _capture_flow(monkeypatch)
    with TestClient(mu_app) as client:
        _login(client)
        assert client.get("/api/gmail/connect").status_code == 200
    assert "login_hint" not in captured


def test_unlink_google_clears_the_sub(mu_app):
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter(User.username == "owner").one()
        user.email = "owner@example.com"
        user.google_sub = "g-1"
        session.commit()
    with TestClient(mu_app) as client:
        _login(client)
        response = client.delete("/api/account/google")
    assert response.status_code == 200
    assert response.json()["googleLinked"] is False
    with Session(mu_app.state.system_engine) as session:
        assert session.query(User).filter(User.username == "owner").one().google_sub is None


def test_unlink_is_refused_when_it_would_lock_the_account_out(mu_app):
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter(User.username == "owner").one()
        user.email = "owner@example.com"
        user.google_sub = "g-1"
        user.password_hash = ""  # Google is the only way in
        session.commit()
    with TestClient(mu_app) as client:
        # Sign in through the Google path is not needed; forge the session.
        from resume_agent.api import auth as auth_module

        with Session(mu_app.state.system_engine) as session:
            user = session.query(User).filter(User.username == "owner").one()
            token = auth_module.issue_user_session(
                mu_app.state.settings,
                user_id=user.id,
                password_hash="",
                epoch=user.session_epoch,
            )
        client.cookies.set("ra_session", token)
        response = client.delete("/api/account/google")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PASSWORD_REQUIRED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_gmail_prewire.py -v`
Expected: FAIL — `KeyError: 'login_hint'`, and 405 on the delete route.

- [ ] **Step 3: Pre-wire `gmail_connect`**

In `api/routers/gmail.py`, replace the `gmail_connect` body:

```python
@router.get("/gmail/connect", response_model=GmailConnectOut)
def gmail_connect(request: Request):
    settings = get_settings_dep(request)
    _require_client(settings)
    flow = _build_flow(settings, _redirect_uri(request))
    # A user who signed in with Google reaches connected Gmail in one click:
    # login_hint skips the account picker, and include_granted_scopes does
    # incremental authorization on the existing grant, so the consent screen
    # shows only the Gmail scopes being added.
    extra: dict[str, str] = {"include_granted_scopes": "true"}
    email = _account_email(request)
    if email:
        extra["login_hint"] = email
    url, _state = flow.authorization_url(
        access_type="offline", prompt="consent", state=_issue_state(request), **extra
    )
    return GmailConnectOut(auth_url=url)


def _account_email(request: Request) -> str:
    context = current_context()
    engine = getattr(request.app.state, "system_engine", None)
    if context is None or engine is None:
        return ""
    from sqlalchemy.orm import Session as SystemSession

    from resume_agent.tenancy.system_db import User

    with SystemSession(engine) as session:
        user = session.get(User, context.user_id)
        return (user.email or "") if user is not None else ""
```

- [ ] **Step 4: Add the unlink handler**

Append to `api/routers/account.py`:

```python
@router.delete("/google", response_model=MeResponse)
def unlink_google(
    request: Request, settings: Settings = Depends(get_settings_dep)
) -> MeResponse:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, context.user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such account")
        if not has_password(user):
            # Google is the only credential; unlinking would lock them out.
            raise ApiException(
                409,
                "PASSWORD_REQUIRED",
                "Set a password before unlinking Google — use password reset.",
            )
        user.google_sub = None
        session.commit()
        session.refresh(user)
        email, username, role, verified = (
            user.email,
            user.username,
            user.role,
            user.email_verified_at,
        )
    if email:
        notice = messages.google_linked(settings.app_base_url)
        request.app.state.mailer.notify(
            to=email,
            subject="A Google account was unlinked from your Resume Agent account",
            body=notice.body,
        )
    return MeResponse(
        username=username,
        email=email,
        email_verified=verified is not None,
        google_linked=False,
        role=cast(Literal["admin", "user"], role),
        auth_required=True,
    )
```

Add `has_password` to the `system_db` import in `account.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q && ruff check src/resume_agent`
Expected: all pass.

- [ ] **Step 6: Regenerate the contract**

Run: `bash scripts/gen_ts_client.sh && .venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent tests/api contracts
git commit -m "Pre-wires Gmail connect for Google accounts and adds a safe unlink"
```

---

**Phase 5 checkpoint.** Run `.venv/Scripts/python.exe -m pytest -q` and `ruff check`. The full backend is done; the web app is still on the old contract.

---

## Phase 6 — Web

### Task 17: `AuthLayout` split canvas

**Files:**

- Create: `web/src/features/auth/AuthLayout.tsx`
- Test: `web/src/features/auth/AuthLayout.test.tsx`

**Interfaces:**

- Produces: `AuthLayout({ title, description, icon, children, footer })` where `title: string`, `description: string`, `icon: ReactNode`, `children: ReactNode`, `footer?: ReactNode`

**Why a fixed split rather than the current centered card:** this flow grows from two screens to six, and their heights differ sharply — a six-box code input is short, a password screen with a strength meter and a Google button is tall. A centered card visibly jumps size between steps. With a fixed split only the right column changes and the composition holds still.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/auth/AuthLayout.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthLayout } from "./AuthLayout";

describe("AuthLayout", () => {
  it("renders the heading, description, and children", () => {
    render(
      <AuthLayout title="Sign in" description="Welcome back">
        <p>Form goes here</p>
      </AuthLayout>,
    );
    expect(
      screen.getByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Welcome back")).toBeInTheDocument();
    expect(screen.getByText("Form goes here")).toBeInTheDocument();
  });

  it("renders the footer when given one", () => {
    render(
      <AuthLayout
        title="Sign in"
        description="d"
        footer={<span>Footer slot</span>}
      >
        <p>c</p>
      </AuthLayout>,
    );
    expect(screen.getByText("Footer slot")).toBeInTheDocument();
  });

  it("hides the decorative brand panel from assistive technology", () => {
    const { container } = render(
      <AuthLayout title="Sign in" description="d">
        <p>c</p>
      </AuthLayout>,
    );
    const panel = container.querySelector("[data-slot='auth-brand']");
    expect(panel).toHaveAttribute("aria-hidden", "true");
  });

  it("exposes exactly one main landmark", () => {
    render(
      <AuthLayout title="Sign in" description="d">
        <p>c</p>
      </AuthLayout>,
    );
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/auth/AuthLayout.test.tsx`
Expected: FAIL — cannot resolve `./AuthLayout`

- [ ] **Step 3: Write `AuthLayout.tsx`**

```tsx
import type { ReactNode } from "react";

/**
 * Two-column auth shell: a decorative brand panel and a fixed-width form
 * column. The split is structural, not decorative — six auth screens of very
 * different heights share this shell, and a centered card would visibly
 * resize between steps.
 */
export function AuthLayout({
  title,
  description,
  icon,
  children,
  footer,
}: {
  title: string;
  description: string;
  icon?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <div
        data-slot="auth-brand"
        aria-hidden="true"
        className="relative hidden overflow-hidden bg-primary text-primary-foreground lg:flex lg:w-[55%] lg:flex-col lg:justify-between lg:p-12"
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,color-mix(in_oklab,var(--primary-foreground)_22%,transparent),transparent_55%)]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,color-mix(in_oklab,var(--primary-foreground)_8%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_oklab,var(--primary-foreground)_8%,transparent)_1px,transparent_1px)] bg-[size:3rem_3rem]" />
        <p className="relative text-lg font-semibold tracking-tight">
          Resume Agent
        </p>
        <div className="relative max-w-md">
          <p className="text-3xl font-semibold leading-tight tracking-tight">
            Every bullet traces back to a fact you actually wrote.
          </p>
          <p className="mt-4 text-sm opacity-80">
            Discover roles, tailor with provenance, and track every application
            from one workspace.
          </p>
        </div>
        <p className="relative text-xs opacity-70">
          Your private command center.
        </p>
      </div>

      <main className="flex w-full items-center justify-center bg-background p-6 lg:w-[45%]">
        <div className="w-full max-w-sm">
          {icon ? (
            <div className="mb-4 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              {icon}
            </div>
          ) : null}
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
          <div className="mt-6">{children}</div>
          {footer ? <div className="mt-6 text-sm">{footer}</div> : null}
        </div>
      </main>
    </div>
  );
}
```

The brand panel uses `color-mix` against `--primary-foreground` rather than a hard-coded white so it reads correctly in both themes without a second gradient definition.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/auth/AuthLayout.test.tsx && npm run lint`
Expected: 4 passed, lint clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/auth/AuthLayout.tsx web/src/features/auth/AuthLayout.test.tsx
git commit -m "Adds the split-canvas auth shell"
```

---

### Task 18: `OtpInput`, strength meter, and Google button

**Files:**

- Create: `web/src/features/auth/OtpInput.tsx`, `web/src/features/auth/strength.ts`, `web/src/features/auth/PasswordStrengthMeter.tsx`, `web/src/features/auth/GoogleButton.tsx`
- Test: `web/src/features/auth/OtpInput.test.tsx`, `web/src/features/auth/strength.test.ts`

**Interfaces:**

- Produces:
  - `OtpInput({ value, onChange, disabled, label })` — `value: string`, `onChange: (next: string) => void`, `label: string`
  - `scorePassword(password: string): { score: 0 | 1 | 2 | 3 | 4; hint: string }`
  - `PasswordStrengthMeter({ password })`
  - `GoogleButton({ mode, invite, disabled })` — `mode: "login" | "register"`, `invite?: string`

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/auth/strength.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { scorePassword } from "./strength";

describe("scorePassword", () => {
  it("scores an empty password at zero", () => {
    expect(scorePassword("").score).toBe(0);
  });

  it("scores a short password low", () => {
    expect(scorePassword("abc").score).toBeLessThanOrEqual(1);
  });

  it("scores a long mixed password high", () => {
    expect(
      scorePassword("quartz-Lantern-42-drift!").score,
    ).toBeGreaterThanOrEqual(3);
  });

  it("penalizes a repeated run", () => {
    expect(scorePassword("aaaaaaaaaaaaaaaa").score).toBeLessThan(
      scorePassword("quartz-Lantern-42-drift!").score,
    );
  });

  it("penalizes a simple sequence", () => {
    expect(scorePassword("abcdefghijklmnop").score).toBeLessThan(4);
  });

  it("always returns a hint string", () => {
    for (const value of ["", "abc", "quartz-Lantern-42-drift!"]) {
      expect(typeof scorePassword(value).hint).toBe("string");
      expect(scorePassword(value).hint.length).toBeGreaterThan(0);
    }
  });
});
```

Create `web/src/features/auth/OtpInput.test.tsx`:

```tsx
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OtpInput } from "./OtpInput";

function Harness({ onChange }: { onChange?: (next: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <OtpInput
      label="Verification code"
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

describe("OtpInput", () => {
  it("renders six boxes under one group label", () => {
    render(<Harness />);
    expect(
      screen.getByRole("group", { name: "Verification code" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(6);
  });

  it("advances to the next box as digits are typed", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const boxes = screen.getAllByRole("textbox");
    await user.click(boxes[0]);
    await user.keyboard("12");
    expect(boxes[0]).toHaveValue("1");
    expect(boxes[1]).toHaveValue("2");
    expect(boxes[2]).toHaveFocus();
  });

  it("ignores non-digit characters", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const boxes = screen.getAllByRole("textbox");
    await user.click(boxes[0]);
    await user.keyboard("a");
    expect(boxes[0]).toHaveValue("");
  });

  it("fills every box from a pasted six-digit code", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const boxes = screen.getAllByRole("textbox");
    await user.click(boxes[0]);
    await user.paste("482913");
    expect(onChange).toHaveBeenLastCalledWith("482913");
    expect(boxes[5]).toHaveValue("3");
  });

  it("moves back on backspace from an empty box", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const boxes = screen.getAllByRole("textbox");
    await user.click(boxes[0]);
    await user.keyboard("12");
    await user.keyboard("{Backspace}");
    expect(boxes[1]).toHaveFocus();
  });

  it("navigates with the arrow keys", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const boxes = screen.getAllByRole("textbox");
    await user.click(boxes[3]);
    await user.keyboard("{ArrowLeft}");
    expect(boxes[2]).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(boxes[3]).toHaveFocus();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/auth/OtpInput.test.tsx src/features/auth/strength.test.ts`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write `strength.ts`**

```ts
/**
 * Advisory-only strength heuristic. The server is the sole authority — this
 * never gates submit, it only tells the user why a password looks weak before
 * they pay a round trip. Deliberately dependency-free: zxcvbn is not worth
 * ~400 KB for a hint.
 */
export type StrengthScore = 0 | 1 | 2 | 3 | 4;

const MIN_LENGTH = 12;

function hasRun(password: string): boolean {
  return /(.)\1{3,}/.test(password);
}

function hasSequence(password: string): boolean {
  const lowered = password.toLowerCase();
  for (let index = 0; index + 3 < lowered.length; index += 1) {
    const codes = [0, 1, 2, 3].map((offset) =>
      lowered.charCodeAt(index + offset),
    );
    if (
      codes.every(
        (code, offset) => offset === 0 || code === codes[offset - 1] + 1,
      )
    ) {
      return true;
    }
  }
  return false;
}

export function scorePassword(password: string): {
  score: StrengthScore;
  hint: string;
} {
  if (!password) return { score: 0, hint: "Use at least 12 characters." };

  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) =>
    pattern.test(password),
  ).length;

  let points = 0;
  if (password.length >= MIN_LENGTH) points += 2;
  else if (password.length >= 8) points += 1;
  if (password.length >= 20) points += 1;
  points += classes >= 3 ? 1 : 0;
  if (hasRun(password) || hasSequence(password)) points -= 2;

  const score = Math.max(0, Math.min(4, points)) as StrengthScore;
  const hint =
    password.length < MIN_LENGTH
      ? `Use at least ${MIN_LENGTH} characters.`
      : hasRun(password) || hasSequence(password)
        ? "Avoid repeated characters and simple sequences."
        : classes < 3
          ? "Mix in uppercase, digits, or symbols."
          : "Looks reasonable — the server makes the final call.";
  return { score, hint };
}
```

- [ ] **Step 4: Write `PasswordStrengthMeter.tsx`**

```tsx
import { scorePassword } from "./strength";

const LABELS = ["Very weak", "Weak", "Fair", "Good", "Strong"] as const;

export function PasswordStrengthMeter({ password }: { password: string }) {
  const { score, hint } = scorePassword(password);
  return (
    <div className="mt-2" data-slot="password-strength">
      <div className="flex gap-1" aria-hidden="true">
        {[0, 1, 2, 3].map((index) => (
          <span
            key={index}
            className={`h-1 flex-1 rounded-full ${
              index < score ? "bg-primary" : "bg-muted"
            }`}
          />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground" role="status">
        {LABELS[score]} — {hint}
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Write `OtpInput.tsx`**

```tsx
import {
  useRef,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";

const LENGTH = 6;

/**
 * Six single-character boxes behaving as one field: paste-aware,
 * auto-advancing, arrow-navigable, and labelled once as a group so a screen
 * reader announces "Verification code", not six anonymous text boxes.
 */
export function OtpInput({
  value,
  onChange,
  disabled,
  label,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  label: string;
}) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = value.padEnd(LENGTH, " ").slice(0, LENGTH).split("");

  const focus = (index: number) => {
    refs.current[Math.max(0, Math.min(LENGTH - 1, index))]?.focus();
  };

  const write = (index: number, digit: string) => {
    const next = digits.map((character, position) =>
      position === index ? digit : character,
    );
    onChange(next.join("").replace(/ /g, ""));
  };

  const handleChange =
    (index: number) => (event: ChangeEvent<HTMLInputElement>) => {
      const digit = event.target.value.replace(/\D/g, "").slice(-1);
      if (!digit) return;
      write(index, digit);
      focus(index + 1);
    };

  const handleKeyDown =
    (index: number) => (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Backspace") {
        event.preventDefault();
        if (digits[index].trim()) {
          write(index, " ");
        } else {
          write(index - 1 >= 0 ? index - 1 : 0, " ");
          focus(index - 1);
        }
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        focus(index - 1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        focus(index + 1);
      }
    };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData
      .getData("text")
      .replace(/\D/g, "")
      .slice(0, LENGTH);
    if (!pasted) return;
    event.preventDefault();
    onChange(pasted);
    focus(pasted.length - 1);
  };

  return (
    <div role="group" aria-label={label} className="flex gap-2">
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(element) => {
            refs.current[index] = element;
          }}
          type="text"
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          maxLength={1}
          disabled={disabled}
          aria-label={`Digit ${index + 1}`}
          value={digit.trim()}
          onChange={handleChange(index)}
          onKeyDown={handleKeyDown(index)}
          onPaste={handlePaste}
          className="size-12 rounded-md border border-input bg-transparent text-center text-lg tabular-nums shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Write `GoogleButton.tsx`**

```tsx
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";

/**
 * Starts the Google flow. The API mints the signed state (carrying mode and
 * the invite), so the client never constructs the authorization URL itself.
 */
export function GoogleButton({
  mode,
  invite,
  disabled,
}: {
  mode: "login" | "register";
  invite?: string;
  disabled?: boolean;
}) {
  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.GET("/api/auth/google/start", {
          params: { query: { mode, ...(invite ? { invite } : {}) } },
        }),
      ),
    onSuccess: (result) => {
      window.location.assign(result.authUrl);
    },
  });

  return (
    <div>
      <Button
        type="button"
        variant="outline"
        className="w-full"
        disabled={disabled || start.isPending}
        onClick={() => start.mutate()}
      >
        {start.isPending ? <Spinner data-icon="inline-start" /> : null}
        Continue with Google
      </Button>
      {start.isError ? (
        <p className="mt-2 text-xs text-destructive" role="alert">
          {start.error.message}
        </p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/auth && npm run lint`
Expected: all pass, lint clean.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/auth
git commit -m "Adds the OTP input, advisory strength meter, and Google start button"
```

---

### Task 19: Rebuild login and register on the new contract

**Files:**

- Modify: `web/src/features/auth/LoginPage.tsx`, `web/src/features/auth/RegisterPage.tsx`
- Test: `web/src/features/auth/LoginPage.test.tsx`, `web/src/features/auth/RegisterPage.test.tsx`

**Interfaces:**

- Consumes: `AuthLayout`, `GoogleButton`, `PasswordStrengthMeter`, `api` client
- Produces: `LoginPage`, `RegisterPage`; register navigates to `/verify-email?email=<address>` on 202

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/auth/LoginPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { LoginPage } from "./LoginPage";

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  it("posts the typed identifier and navigates on success", async () => {
    let body: unknown;
    server.use(
      http.post("/api/auth/login", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          username: "ada",
          email: "ada@example.com",
          authRequired: true,
        });
      }),
    );
    const user = userEvent.setup();
    wrap();
    await user.type(screen.getByLabelText(/email/i), "ada@example.com");
    await user.type(
      screen.getByLabelText(/password/i),
      "quartz-lantern-42-drift",
    );
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(body).toEqual({
      identifier: "ada@example.com",
      password: "quartz-lantern-42-drift",
    });
  });

  it("shows the server error message on a rejected sign-in", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          {
            error: {
              code: "UNAUTHORIZED",
              message: "Invalid email or password",
            },
          },
          { status: 401 },
        ),
      ),
    );
    const user = userEvent.setup();
    wrap();
    await user.type(screen.getByLabelText(/email/i), "ada@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrong-password-here");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(
      await screen.findByText(/invalid email or password/i),
    ).toBeInTheDocument();
  });

  it("offers Google and forgot-password entry points", () => {
    wrap();
    expect(
      screen.getByRole("button", { name: /continue with google/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /forgot/i })).toBeInTheDocument();
  });
});
```

Create `web/src/features/auth/RegisterPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { RegisterPage } from "./RegisterPage";

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify-email" element={<div>Verify step</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/email/i), "ada@example.com");
  await user.type(
    screen.getByLabelText(/^password$/i),
    "quartz-lantern-42-drift",
  );
  await user.type(screen.getByLabelText(/invite/i), "inv_abcdefgh");
}

describe("RegisterPage", () => {
  it("posts the signup and advances to the verify step", async () => {
    let body: unknown;
    server.use(
      http.post("/api/auth/register", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ status: "sent" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    wrap();
    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Verify step")).toBeInTheDocument();
    expect(body).toMatchObject({
      email: "ada@example.com",
      password: "quartz-lantern-42-drift",
      inviteCode: "inv_abcdefgh",
    });
  });

  it("surfaces a weak-password rejection from the server", async () => {
    server.use(
      http.post("/api/auth/register", () =>
        HttpResponse.json(
          {
            error: {
              code: "PASSWORD_WEAK",
              message: "That password is too common",
            },
          },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    wrap();
    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText(/too common/i)).toBeInTheDocument();
  });

  it("shows the advisory strength meter as the password is typed", async () => {
    const user = userEvent.setup();
    const { container } = wrap();
    await user.type(screen.getByLabelText(/^password$/i), "abc");
    expect(
      container.querySelector("[data-slot='password-strength']"),
    ).toBeInTheDocument();
  });

  it("never blocks submit on a weak-looking password", async () => {
    const user = userEvent.setup();
    wrap();
    await user.type(screen.getByLabelText(/^password$/i), "abc");
    expect(
      screen.getByRole("button", { name: /create account/i }),
    ).toBeEnabled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/auth/LoginPage.test.tsx src/features/auth/RegisterPage.test.tsx`
Expected: FAIL — the pages still render a Username field and post `username`.

- [ ] **Step 3: Rewrite `LoginPage.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { GoogleButton } from "./GoogleButton";

export function LoginPage() {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/auth/login", { body: { identifier, password } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };

  return (
    <AuthLayout
      title="Sign in"
      description="Welcome back to your private command center."
      icon={<KeyRoundIcon aria-hidden="true" />}
      footer={
        <span className="text-muted-foreground">
          Need an account?{" "}
          <Link
            className="text-foreground underline underline-offset-4"
            to="/register"
          >
            Register with an invite
          </Link>
        </span>
      }
    >
      <GoogleButton mode="login" />
      <div className="my-5 flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="text-xs text-muted-foreground">or</span>
        <Separator className="flex-1" />
      </div>
      <form onSubmit={submit}>
        <FieldGroup>
          <Field data-invalid={login.isError || undefined}>
            <FieldLabel htmlFor="login-identifier">Email</FieldLabel>
            <Input
              id="login-identifier"
              type="text"
              autoComplete="username"
              value={identifier}
              disabled={login.isPending}
              aria-invalid={login.isError || undefined}
              onChange={(event) => setIdentifier(event.target.value)}
              required
            />
          </Field>
          <Field data-invalid={login.isError || undefined}>
            <div className="flex items-center justify-between">
              <FieldLabel htmlFor="login-password">Password</FieldLabel>
              <Link
                className="text-xs text-muted-foreground underline underline-offset-4"
                to="/forgot-password"
              >
                Forgot password?
              </Link>
            </div>
            <Input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              disabled={login.isPending}
              aria-invalid={login.isError || undefined}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            {login.isError && <FieldError>{login.error.message}</FieldError>}
          </Field>
        </FieldGroup>
        <Button
          className="mt-6 w-full"
          type="submit"
          disabled={login.isPending}
        >
          {login.isPending && <Spinner data-icon="inline-start" />}
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
```

The field is labelled "Email" but typed `text` with `autoComplete="username"`, because a pre-email account still signs in with its username and `type="email"` would let the browser block that submission.

- [ ] **Step 4: Rewrite `RegisterPage.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { GoogleButton } from "./GoogleButton";
import { PasswordStrengthMeter } from "./PasswordStrengthMeter";

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const navigate = useNavigate();
  const register = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/auth/register", {
          body: {
            email,
            password,
            inviteCode,
            displayName: displayName || undefined,
          },
        }),
      ),
    onSuccess: () => {
      // No account exists yet — the code is what creates it.
      navigate(`/verify-email?email=${encodeURIComponent(email)}`, {
        replace: true,
      });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    register.mutate();
  };

  return (
    <AuthLayout
      title="Create your workspace"
      description="You need an invite code and an email address you can read right now."
      icon={<UserPlus aria-hidden="true" />}
      footer={
        <span className="text-muted-foreground">
          Already have an account?{" "}
          <Link
            className="text-foreground underline underline-offset-4"
            to="/login"
          >
            Sign in
          </Link>
        </span>
      }
    >
      <GoogleButton mode="register" invite={inviteCode || undefined} />
      <div className="my-5 flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="text-xs text-muted-foreground">or</span>
        <Separator className="flex-1" />
      </div>
      <form onSubmit={submit}>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="register-email">Email</FieldLabel>
            <Input
              id="register-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="register-password">Password</FieldLabel>
            <Input
              id="register-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <PasswordStrengthMeter password={password} />
          </Field>
          <Field>
            <FieldLabel htmlFor="register-name">
              Display name (optional)
            </FieldLabel>
            <Input
              id="register-name"
              autoComplete="name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </Field>
          <Field data-invalid={register.isError || undefined}>
            <FieldLabel htmlFor="register-invite">Invite code</FieldLabel>
            <Input
              id="register-invite"
              autoComplete="off"
              value={inviteCode}
              onChange={(event) => setInviteCode(event.target.value)}
              aria-invalid={register.isError || undefined}
              required
            />
            {register.isError && (
              <FieldError>{register.error.message}</FieldError>
            )}
          </Field>
        </FieldGroup>
        <Button
          className="mt-6 w-full"
          type="submit"
          disabled={register.isPending}
        >
          {register.isPending && <Spinner data-icon="inline-start" />}
          {register.isPending ? "Sending code…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
```

The invite field feeds `GoogleButton` too, so the Google path carries the same invite inside the signed state.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/auth && npm run lint`
Expected: all pass. The pre-existing `auth.test.tsx` cases that assert a Username label will fail — update them to Email; that is the expected contract change.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/auth
git commit -m "Rebuilds login and register on the split canvas and email contract"
```

---

### Task 20: Verify, forgot, reset, complete-profile, and routing

**Files:**

- Create: `web/src/features/auth/VerifyEmailPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`, `CompleteProfilePage.tsx`
- Modify: `web/src/features/auth/AuthGate.tsx`, `web/src/app/router.tsx`
- Test: `web/src/features/auth/VerifyEmailPage.test.tsx`, `web/src/features/auth/ResetPasswordPage.test.tsx`, `web/src/features/auth/AuthGate.test.tsx`

**Interfaces:**

- Consumes: `AuthLayout`, `OtpInput`, `PasswordStrengthMeter`, `useMe`
- Produces: the four page components; `AuthGate` redirects to `/complete-profile` when `needsEmail` is true

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/auth/VerifyEmailPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { VerifyEmailPage } from "./VerifyEmailPage";

function wrap(search = "?email=ada%40example.com") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/verify-email${search}`]}>
        <Routes>
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/" element={<div>Dashboard</div>} />
          <Route path="/register" element={<div>Register</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("VerifyEmailPage", () => {
  it("shows the address the code went to", () => {
    wrap();
    expect(screen.getByText(/ada@example\.com/)).toBeInTheDocument();
  });

  it("submits the pasted code and signs in", async () => {
    let body: unknown;
    server.use(
      http.post("/api/auth/verify-email", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          username: "ada",
          email: "ada@example.com",
          authRequired: true,
        });
      }),
    );
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getAllByRole("textbox")[0]);
    await user.paste("482913");
    await user.click(screen.getByRole("button", { name: /verify/i }));
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(body).toEqual({ email: "ada@example.com", code: "482913" });
  });

  it("shows the error when the code is wrong", async () => {
    server.use(
      http.post("/api/auth/verify-email", () =>
        HttpResponse.json(
          {
            error: { code: "CODE_INVALID", message: "That code is not valid" },
          },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getAllByRole("textbox")[0]);
    await user.paste("000000");
    await user.click(screen.getByRole("button", { name: /verify/i }));
    expect(await screen.findByText(/not valid/i)).toBeInTheDocument();
  });

  it("keeps verify disabled until six digits are entered", async () => {
    const user = userEvent.setup();
    wrap();
    expect(screen.getByRole("button", { name: /verify/i })).toBeDisabled();
    await user.click(screen.getAllByRole("textbox")[0]);
    await user.paste("4829");
    expect(screen.getByRole("button", { name: /verify/i })).toBeDisabled();
  });

  it("sends the user back to register when no address is in the URL", () => {
    wrap("");
    expect(screen.getByText("Register")).toBeInTheDocument();
  });

  it("can request a fresh code", async () => {
    let resent = false;
    server.use(
      http.post("/api/auth/resend-code", () => {
        resent = true;
        return HttpResponse.json({ status: "sent" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getByRole("button", { name: /resend/i }));
    await screen.findByText(/new code/i);
    expect(resent).toBe(true);
  });
});
```

Create `web/src/features/auth/ResetPasswordPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { ResetPasswordPage } from "./ResetPasswordPage";

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={["/reset-password?email=ada%40example.com"]}
      >
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/" element={<div>Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResetPasswordPage", () => {
  it("submits the code and new password, then signs in", async () => {
    let body: unknown;
    server.use(
      http.post("/api/auth/password/reset", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          username: "ada",
          email: "ada@example.com",
          authRequired: true,
        });
      }),
    );
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getAllByRole("textbox")[0]);
    await user.paste("482913");
    await user.type(
      screen.getByLabelText(/new password/i),
      "cobalt-meridian-77-x",
    );
    await user.click(screen.getByRole("button", { name: /reset password/i }));
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(body).toEqual({
      email: "ada@example.com",
      code: "482913",
      newPassword: "cobalt-meridian-77-x",
    });
  });

  it("surfaces a rejected new password", async () => {
    server.use(
      http.post("/api/auth/password/reset", () =>
        HttpResponse.json(
          {
            error: {
              code: "PASSWORD_WEAK",
              message: "That password is too common",
            },
          },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getAllByRole("textbox")[0]);
    await user.paste("482913");
    await user.type(screen.getByLabelText(/new password/i), "passwordpassword");
    await user.click(screen.getByRole("button", { name: /reset password/i }));
    expect(await screen.findByText(/too common/i)).toBeInTheDocument();
  });
});
```

Append to `web/src/features/auth/AuthGate.test.tsx` (or the existing `auth.test.tsx`):

```tsx
it("routes a pre-email account to complete-profile", async () => {
  server.use(
    http.get("/api/auth/me", () =>
      HttpResponse.json({
        username: "owner",
        authRequired: true,
        needsEmail: true,
      }),
    ),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/complete-profile"
            element={<div>Complete profile</div>}
          />
          <Route
            path="/"
            element={
              <AuthGate>
                <div>App content</div>
              </AuthGate>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Complete profile")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/auth`
Expected: FAIL — the three page modules do not exist and `AuthGate` ignores `needsEmail`.

- [ ] **Step 3: Write `VerifyEmailPage.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { OtpInput } from "./OtpInput";

const CODE_LENGTH = 6;

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const email = params.get("email") ?? "";
  const [code, setCode] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const verify = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/auth/verify-email", { body: { email, code } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });
  const resend = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/auth/resend-code", { body: { email } })),
    onSuccess: () => setCode(""),
  });

  // No address means no pending signup to verify.
  if (!email) return <Navigate to="/register" replace />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    verify.mutate();
  };

  return (
    <AuthLayout
      title="Check your email"
      description={`We sent a six-digit code to ${email}. It expires in 15 minutes.`}
      icon={<MailCheck aria-hidden="true" />}
    >
      <form onSubmit={submit}>
        <OtpInput
          label="Verification code"
          value={code}
          onChange={setCode}
          disabled={verify.isPending}
        />
        {verify.isError && (
          <p className="mt-3 text-sm text-destructive" role="alert">
            {verify.error.message}
          </p>
        )}
        {resend.isSuccess && (
          <p className="mt-3 text-sm text-muted-foreground" role="status">
            A new code is on its way.
          </p>
        )}
        <Button
          className="mt-6 w-full"
          type="submit"
          disabled={code.length < CODE_LENGTH || verify.isPending}
        >
          {verify.isPending && <Spinner data-icon="inline-start" />}
          {verify.isPending ? "Verifying…" : "Verify and continue"}
        </Button>
        <Button
          className="mt-2 w-full"
          type="button"
          variant="ghost"
          disabled={resend.isPending}
          onClick={() => resend.mutate()}
        >
          Resend code
        </Button>
      </form>
    </AuthLayout>
  );
}
```

- [ ] **Step 4: Write `ForgotPasswordPage.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { LifeBuoy } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const navigate = useNavigate();
  const forgot = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/auth/password/forgot", { body: { email } })),
    // The endpoint answers identically for known and unknown addresses, so
    // the UI must not branch on the result either.
    onSuccess: () =>
      navigate(`/reset-password?email=${encodeURIComponent(email)}`, {
        replace: true,
      }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    forgot.mutate();
  };

  return (
    <AuthLayout
      title="Reset your password"
      description="Enter your email and we'll send a single-use code."
      icon={<LifeBuoy aria-hidden="true" />}
      footer={
        <Link
          className="text-muted-foreground underline underline-offset-4"
          to="/login"
        >
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={submit}>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="forgot-email">Email</FieldLabel>
            <Input
              id="forgot-email"
              type="email"
              autoComplete="email"
              value={email}
              disabled={forgot.isPending}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </Field>
        </FieldGroup>
        <Button
          className="mt-6 w-full"
          type="submit"
          disabled={forgot.isPending}
        >
          {forgot.isPending && <Spinner data-icon="inline-start" />}
          {forgot.isPending ? "Sending…" : "Send reset code"}
        </Button>
      </form>
    </AuthLayout>
  );
}
```

- [ ] **Step 5: Write `ResetPasswordPage.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { OtpInput } from "./OtpInput";
import { PasswordStrengthMeter } from "./PasswordStrengthMeter";

const CODE_LENGTH = 6;

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const email = params.get("email") ?? "";
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const reset = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/auth/password/reset", {
          body: { email, code, newPassword },
        }),
      ),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });

  if (!email) return <Navigate to="/forgot-password" replace />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    reset.mutate();
  };

  return (
    <AuthLayout
      title="Choose a new password"
      description={`Enter the code sent to ${email} and pick a new password. This signs out every other device.`}
      icon={<ShieldCheck aria-hidden="true" />}
    >
      <form onSubmit={submit}>
        <OtpInput
          label="Reset code"
          value={code}
          onChange={setCode}
          disabled={reset.isPending}
        />
        <FieldGroup className="mt-5">
          <Field>
            <FieldLabel htmlFor="reset-password">New password</FieldLabel>
            <Input
              id="reset-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              disabled={reset.isPending}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
            <PasswordStrengthMeter password={newPassword} />
          </Field>
        </FieldGroup>
        {reset.isError && (
          <p className="mt-3 text-sm text-destructive" role="alert">
            {reset.error.message}
          </p>
        )}
        <Button
          className="mt-6 w-full"
          type="submit"
          disabled={
            code.length < CODE_LENGTH || !newPassword || reset.isPending
          }
        >
          {reset.isPending && <Spinner data-icon="inline-start" />}
          {reset.isPending ? "Resetting…" : "Reset password"}
        </Button>
      </form>
    </AuthLayout>
  );
}
```

- [ ] **Step 6: Write `CompleteProfilePage.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AtSign } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { OtpInput } from "./OtpInput";

const CODE_LENGTH = 6;

/**
 * One-time migration screen for accounts created before email identity.
 * Deletable once every account has a verified address.
 */
export function CompleteProfilePage() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const request = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/account/email", { body: { email } })),
    onSuccess: () => setSent(true),
  });
  const confirm = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/account/email/verify", { body: { email, code } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    (sent ? confirm : request).mutate();
  };

  const active = sent ? confirm : request;

  return (
    <AuthLayout
      title="Add your email"
      description="Your account predates email sign-in. Add an address so you can recover your password."
      icon={<AtSign aria-hidden="true" />}
    >
      <form onSubmit={submit}>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="complete-email">Email</FieldLabel>
            <Input
              id="complete-email"
              type="email"
              autoComplete="email"
              value={email}
              disabled={sent || active.isPending}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </Field>
        </FieldGroup>
        {sent && (
          <div className="mt-5">
            <OtpInput
              label="Verification code"
              value={code}
              onChange={setCode}
              disabled={confirm.isPending}
            />
          </div>
        )}
        {active.isError && (
          <p className="mt-3 text-sm text-destructive" role="alert">
            {active.error.message}
          </p>
        )}
        <Button
          className="mt-6 w-full"
          type="submit"
          disabled={active.isPending || (sent && code.length < CODE_LENGTH)}
        >
          {active.isPending && <Spinner data-icon="inline-start" />}
          {sent ? "Verify and continue" : "Send verification code"}
        </Button>
      </form>
    </AuthLayout>
  );
}
```

- [ ] **Step 7: Gate on `needsEmail` and register the routes**

In `AuthGate.tsx`, before the existing sign-in redirect:

```tsx
if (me.data.authRequired && !me.data.username) {
  return <Navigate to="/login" replace />;
}
if (me.data.needsEmail) {
  return <Navigate to="/complete-profile" replace />;
}
```

In `web/src/app/router.tsx`, add the lazy imports beside the existing ones and four routes beside `/login` and `/register` (line 123):

```tsx
const VerifyEmailPage = lazy(() =>
  import("@/features/auth/VerifyEmailPage").then((m) => ({
    default: m.VerifyEmailPage,
  })),
);
const ForgotPasswordPage = lazy(() =>
  import("@/features/auth/ForgotPasswordPage").then((m) => ({
    default: m.ForgotPasswordPage,
  })),
);
const ResetPasswordPage = lazy(() =>
  import("@/features/auth/ResetPasswordPage").then((m) => ({
    default: m.ResetPasswordPage,
  })),
);
const CompleteProfilePage = lazy(() =>
  import("@/features/auth/CompleteProfilePage").then((m) => ({
    default: m.CompleteProfilePage,
  })),
);
```

```tsx
  { path: "/verify-email", element: page(<VerifyEmailPage />) },
  { path: "/forgot-password", element: page(<ForgotPasswordPage />) },
  { path: "/reset-password", element: page(<ResetPasswordPage />) },
  { path: "/complete-profile", element: page(<CompleteProfilePage />) },
```

`/complete-profile` sits **outside** the `AuthGate`-wrapped tree; otherwise the gate would redirect to it from itself in a loop.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd web && npx vitest run && npm run lint && npm run build`
Expected: all pass, lint clean, build succeeds.

- [ ] **Step 9: Commit**

```bash
git add web/src
git commit -m "Adds the verify, forgot, reset, and complete-profile screens with routing"
```

---

### Task 21: Account security card

**Files:**

- Create: `web/src/features/account/SecurityCard.tsx`
- Modify: `web/src/features/account/AccountPage.tsx`
- Test: `web/src/features/account/SecurityCard.test.tsx`

**Interfaces:**

- Consumes: `useMe`, `api`
- Produces: `SecurityCard()` rendering Google link state and "Sign out everywhere"

- [ ] **Step 1: Write the failing test**

Create `web/src/features/account/SecurityCard.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { SecurityCard } from "./SecurityCard";

function wrap(me: Record<string, unknown>) {
  server.use(http.get("/api/auth/me", () => HttpResponse.json(me)));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SecurityCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SecurityCard", () => {
  it("offers to connect Google when it is not linked", async () => {
    wrap({
      username: "ada",
      email: "ada@example.com",
      authRequired: true,
      googleLinked: false,
    });
    expect(
      await screen.findByRole("button", { name: /continue with google/i }),
    ).toBeInTheDocument();
  });

  it("offers to unlink when Google is linked", async () => {
    wrap({
      username: "ada",
      email: "ada@example.com",
      authRequired: true,
      googleLinked: true,
    });
    expect(
      await screen.findByRole("button", { name: /unlink/i }),
    ).toBeInTheDocument();
  });

  it("surfaces the lockout refusal when unlinking would lock the account out", async () => {
    server.use(
      http.delete("/api/account/google", () =>
        HttpResponse.json(
          {
            error: {
              code: "PASSWORD_REQUIRED",
              message: "Set a password before unlinking Google",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    wrap({
      username: "ada",
      email: "ada@example.com",
      authRequired: true,
      googleLinked: true,
    });
    await user.click(await screen.findByRole("button", { name: /unlink/i }));
    expect(
      await screen.findByText(/set a password before unlinking/i),
    ).toBeInTheDocument();
  });

  it("signs out other devices", async () => {
    let revoked = false;
    server.use(
      http.post("/api/account/sessions/revoke-all", () => {
        revoked = true;
        return HttpResponse.json({ status: "ok" });
      }),
    );
    const user = userEvent.setup();
    wrap({
      username: "ada",
      email: "ada@example.com",
      authRequired: true,
      googleLinked: false,
    });
    await user.click(
      await screen.findByRole("button", { name: /sign out everywhere/i }),
    );
    await screen.findByText(/signed out/i);
    expect(revoked).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/account/SecurityCard.test.tsx`
Expected: FAIL — cannot resolve `./SecurityCard`

- [ ] **Step 3: Write `SecurityCard.tsx`**

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { api, unwrap } from "@/lib/api/client";
import { GoogleButton } from "@/features/auth/GoogleButton";
import { useMe } from "@/features/auth/AuthGate";

export function SecurityCard() {
  const me = useMe();
  const queryClient = useQueryClient();

  const unlink = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/account/google")),
    onSuccess: (next) => queryClient.setQueryData(["auth", "me"], next),
  });
  const revokeAll = useMutation({
    mutationFn: () => unwrap(api.POST("/api/account/sessions/revoke-all")),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Security</CardTitle>
        <CardDescription>
          Sign-in methods and active sessions for this account.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <p className="text-sm font-medium">Google sign-in</p>
          <p className="mb-3 text-sm text-muted-foreground">
            {me.data?.googleLinked
              ? "You can sign in with Google."
              : "Link Google to sign in with one click."}
          </p>
          {me.data?.googleLinked ? (
            <Button
              variant="outline"
              disabled={unlink.isPending}
              onClick={() => unlink.mutate()}
            >
              Unlink Google
            </Button>
          ) : (
            <GoogleButton mode="login" />
          )}
          {unlink.isError && (
            <p className="mt-2 text-sm text-destructive" role="alert">
              {unlink.error.message}
            </p>
          )}
        </div>

        <Separator />

        <div>
          <p className="text-sm font-medium">Active sessions</p>
          <p className="mb-3 text-sm text-muted-foreground">
            Signs out every other device. You stay signed in here.
          </p>
          <Button
            variant="outline"
            disabled={revokeAll.isPending}
            onClick={() => revokeAll.mutate()}
          >
            Sign out everywhere
          </Button>
          {revokeAll.isSuccess && (
            <p className="mt-2 text-sm text-muted-foreground" role="status">
              Other devices have been signed out.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Mount it on the account page**

In `web/src/features/account/AccountPage.tsx`, render `<SecurityCard />` immediately after `<PasswordCard />`, importing it from `./SecurityCard`.

- [ ] **Step 5: Warn the admin when mail is not configured**

This is the guard against the riskiest line in the design — a production box
running `NullMailer` and logging live verification codes instead of sending
them. Add to `web/src/features/admin/AdminPage.tsx`, above the existing
content:

```tsx
function MailWarning() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => unwrap(api.GET("/api/health")),
    staleTime: 60_000,
  });
  if (health.data?.mailConfigured !== false) return null;
  return (
    <Alert variant="destructive" className="mb-6">
      <AlertTitle>Email delivery is not configured</AlertTitle>
      <AlertDescription>
        SMTP_HOST is unset, so verification and password-reset codes are being
        written to the server log instead of sent. Nobody can register or
        recover an account until this is fixed.
      </AlertDescription>
    </Alert>
  );
}
```

Render `<MailWarning />` at the top of the admin page, importing `useQuery`
from `@tanstack/react-query`, `api`/`unwrap` from `@/lib/api/client`, and
`Alert`, `AlertTitle`, `AlertDescription` from `@/components/ui/alert`.

Add a test in `web/src/features/admin/MailWarning.test.tsx` asserting the
alert renders when `mailConfigured` is `false` and is absent when it is `true`.

- [ ] **Step 6: Run the whole web suite**

Run: `cd web && npx vitest run && npm run lint && npm run build`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/account web/src/features/admin
git commit -m "Adds the account security card and the unconfigured-mail admin warning"
```

---

## Final verification

- [ ] **Step 1: Full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Lint**

Run: `ruff check`
Expected: clean.

- [ ] **Step 3: Full web suite and production build**

Run: `cd web && npm run test:run && npm run lint && npm run build`
Expected: all pass.

- [ ] **Step 4: Contract drift gate**

Run: `bash scripts/gen_ts_client.sh && git diff --exit-code contracts`
Expected: no diff — the contract was regenerated in Tasks 13 and 16 and committed.

- [ ] **Step 5: Confirm no code leaks into a response**

Run: `grep -rn "code" src/resume_agent/api/schemas/auth_email.py`
Expected: `code` appears only on **request** models (`VerifyEmailRequest`, `ResetPasswordRequest`), never on `CodeSentResponse` or `MeResponse`.

- [ ] **Step 6: Update CLAUDE.md**

Add a section documenting: the two mail actors and why `gmail.send` stays out of scope; the register-then-verify ordering rule; `session_epoch` as the revocation mechanism; the `password_hash == ""` sentinel; and the legacy username fallback with the note that it is deletable once every row has an email.

- [ ] **Step 7: Commit and open the PR**

```bash
git add CLAUDE.md
git commit -m "Documents the auth invariants added by email identity and Google sign-in"
git push -u origin feat/auth-email-verification-oauth
gh pr create --base dev --title "Email-verified accounts, Google sign-in, and auth hardening" --body "Implements docs/superpowers/specs/2026-07-28-auth-email-verification-oauth-design.md"
```

## Deployment notes

Set on Railway before merging to `main`:

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` — without these the app runs with `NullMailer` and **logs verification codes instead of sending them**. Confirm `GET /api/health` reports `mailConfigured: true` after deploy.
- `APP_BASE_URL` — the public origin, e.g. `https://resume-agent.up.railway.app`. Blank only drops the links from notice emails.
- `AUTH_EMAIL` — only used when bootstrapping an empty `users` table.
- Add `https://<host>/api/auth/google/callback` to the Google OAuth client's authorized redirect URIs. The existing Gmail callback URI stays as it is.

Every existing session cookie is invalidated by the deploy (the session HMAC key material changed), and every existing account must sign in by username once, then adopt an email at `/complete-profile`.
