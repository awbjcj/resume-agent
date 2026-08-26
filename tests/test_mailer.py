"""Delivery-failure behaviour of the platform mailer.

A failed send surfaces as a bare ``503 MAIL_UNAVAILABLE`` at the API edge, so
the delivery cause has to be recorded here or it is lost for good.
"""

import json
import logging
import smtplib
from typing import Self

import httpx
import pytest

from resume_agent.config import Settings
from resume_agent.mail.mailer import (
    RESEND_ENDPOINT,
    MailDeliveryError,
    NullMailer,
    ResendMailer,
    SmtpMailer,
    build_mailer,
    mail_configured,
)

SECRET = "app-password-not-loggable"
RESEND_KEY = "re_live_key_not_loggable"


def make_settings(**overrides: object) -> Settings:
    """Explicit kwargs so the developer's real ``.env`` never leaks in."""
    base: dict[str, object] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "sender@example.com",
        "smtp_password": SECRET,
        "smtp_from": "sender@example.com",
        "smtp_starttls": True,
        "resend_api_key": "",
        "mail_from": "",
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
    # codeql[py/incomplete-url-substring-sanitization] -- Assertion only; no URL is constructed or trusted.
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


# --- Resend HTTPS backend -------------------------------------------------
#
# Railway disables outbound SMTP below the Pro plan, so port 587 fails with
# ENETUNREACH no matter how the credentials are set. An HTTPS transactional
# API is the only delivery path available on those plans.


def make_resend_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "resend_api_key": RESEND_KEY,
        "mail_from": "noreply@example.com",
        "smtp_host": "",
        "smtp_username": "",
        "smtp_password": "",
        "smtp_from": "",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def resend_client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "e1"})


def reject_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(403, json={"message": "The example.com domain is not verified"})


def test_resend_key_alone_configures_mail() -> None:
    """An HTTPS key is a complete mail setup; no SMTP host is involved."""
    settings = make_resend_settings()
    assert mail_configured(settings) is True
    assert isinstance(build_mailer(settings), ResendMailer)


def test_resend_wins_when_both_backends_are_configured() -> None:
    """Setting the key is the explicit opt-out from unreachable SMTP."""
    settings = make_resend_settings(smtp_host="smtp.example.com")
    assert isinstance(build_mailer(settings), ResendMailer)


def test_neither_backend_still_selects_the_null_mailer() -> None:
    assert isinstance(build_mailer(make_resend_settings(resend_api_key="")), NullMailer)


def test_resend_send_posts_the_message() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "e1"})

    mailer = ResendMailer(make_resend_settings(), client=resend_client(handler))
    mailer.send(to="user@example.com", subject="Verify", body="code 123")

    assert seen["url"] == RESEND_ENDPOINT
    assert seen["auth"] == f"Bearer {RESEND_KEY}"
    assert seen["payload"] == {
        "from": "noreply@example.com",
        "to": ["user@example.com"],
        "subject": "Verify",
        "text": "code 123",
    }


def test_resend_falls_back_to_the_smtp_sender() -> None:
    """An existing deploy already has SMTP_FROM set; it must not need renaming."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "e1"})

    settings = make_resend_settings(mail_from="", smtp_from="legacy@example.com")
    ResendMailer(settings, client=resend_client(handler)).send(
        to="user@example.com", subject="Verify", body="code"
    )

    assert seen["payload"]["from"] == "legacy@example.com"  # type: ignore[index]


def test_resend_rejection_logs_the_api_detail(caplog: pytest.LogCaptureFixture) -> None:
    """Resend explains refusals in the body; a bare status is undiagnosable."""
    mailer = ResendMailer(make_resend_settings(), client=resend_client(reject_handler))

    with (
        caplog.at_level(logging.WARNING, logger="resume_agent.mail.mailer"),
        pytest.raises(MailDeliveryError) as caught,
    ):
        mailer.send(to="user@example.com", subject="Verify", body="code")

    assert "domain is not verified" in str(caught.value)
    assert "403" in caplog.text
    assert "user@example.com" in caplog.text


def test_resend_failure_never_logs_the_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mailer = ResendMailer(make_resend_settings(), client=resend_client(reject_handler))

    with (
        caplog.at_level(logging.DEBUG, logger="resume_agent.mail.mailer"),
        pytest.raises(MailDeliveryError) as caught,
    ):
        mailer.send(to="user@example.com", subject="Verify", body="code")

    assert RESEND_KEY not in caplog.text
    assert RESEND_KEY not in str(caught.value)


def test_resend_transport_failure_raises_delivery_error() -> None:
    """A network fault must arrive as MailDeliveryError, not a raw httpx error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    mailer = ResendMailer(make_resend_settings(), client=resend_client(handler))

    with pytest.raises(MailDeliveryError):
        mailer.send(to="user@example.com", subject="Verify", body="code")


def test_resend_successful_send_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mailer = ResendMailer(make_resend_settings(), client=resend_client(ok_handler))

    with caplog.at_level(logging.WARNING, logger="resume_agent.mail.mailer"):
        mailer.send(to="user@example.com", subject="Verify", body="code")

    assert caplog.text == ""


def test_resend_notify_swallows_delivery_failure() -> None:
    """Security notices never roll back a completed state change."""
    mailer = ResendMailer(make_resend_settings(), client=resend_client(reject_handler))

    mailer.notify(to="user@example.com", subject="Password changed", body="fyi")
