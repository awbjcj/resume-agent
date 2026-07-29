"""Delivery-failure behaviour of the platform mailer.

A failed send surfaces as a bare ``503 MAIL_UNAVAILABLE`` at the API edge, so
the SMTP cause has to be recorded here or it is lost for good.
"""

import logging
import smtplib
from typing import Self

import pytest

from resume_agent.config import Settings
from resume_agent.mail.mailer import (
    MailDeliveryError,
    NullMailer,
    SmtpMailer,
    build_mailer,
)


SECRET = "app-password-not-loggable"


def make_settings(**overrides: object) -> Settings:
    """Explicit kwargs so the developer's real ``.env`` never leaks in."""
    base: dict[str, object] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "sender@example.com",
        "smtp_password": SECRET,
        "smtp_from": "sender@example.com",
        "smtp_starttls": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class FakeSMTP:
    """Stands in for ``smtplib.SMTP``; fails at the configured step."""

    def __init__(self, fail_with: BaseException | None = None) -> None:
        self.fail_with = fail_with
        self.sent: list[object] = []

    def __call__(self, host: str, port: int, timeout: int = 0) -> "FakeSMTP":
        self.host, self.port = host, port
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def send_message(self, message: object) -> None:
        self.sent.append(message)


AUTH_REJECTED = smtplib.SMTPAuthenticationError(
    535, b"5.7.8 Username and Password not accepted."
)


def test_failed_send_logs_the_smtp_cause(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Without this the API's 503 is undiagnosable from the server log."""
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP(fail_with=AUTH_REJECTED))
    mailer = SmtpMailer(make_settings())

    with (
        caplog.at_level(logging.WARNING, logger="resume_agent.mail.mailer"),
        pytest.raises(MailDeliveryError),
    ):
        mailer.send(to="user@example.com", subject="Verify", body="code")

    logged = caplog.text
    assert "535" in logged
    assert "Username and Password not accepted" in logged
    assert "smtp.example.com" in logged
    assert "user@example.com" in logged


def test_failed_send_never_logs_the_password(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Logging around a credential rejection must not spill the credential."""
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP(fail_with=AUTH_REJECTED))
    mailer = SmtpMailer(make_settings())

    with (
        caplog.at_level(logging.DEBUG, logger="resume_agent.mail.mailer"),
        pytest.raises(MailDeliveryError) as caught,
    ):
        mailer.send(to="user@example.com", subject="Verify", body="code")

    assert SECRET not in caplog.text
    assert SECRET not in str(caught.value)


def test_delivery_error_carries_the_smtp_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raised error keeps the cause so callers may log or chain it."""
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP(fail_with=AUTH_REJECTED))
    mailer = SmtpMailer(make_settings())

    with pytest.raises(MailDeliveryError) as caught:
        mailer.send(to="user@example.com", subject="Verify", body="code")

    assert "535" in str(caught.value)
    assert isinstance(caught.value.__cause__, smtplib.SMTPAuthenticationError)


def test_successful_send_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The new logging is a failure path only; a good send stays quiet."""
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP())
    mailer = SmtpMailer(make_settings())

    with caplog.at_level(logging.WARNING, logger="resume_agent.mail.mailer"):
        mailer.send(to="user@example.com", subject="Verify", body="code")

    assert caplog.text == ""


def test_unconfigured_host_selects_the_null_mailer() -> None:
    """No SMTP host is a working local setup, not a delivery failure."""
    assert isinstance(build_mailer(make_settings(smtp_host="")), NullMailer)
    assert isinstance(build_mailer(make_settings()), SmtpMailer)
