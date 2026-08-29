import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from resume_agent.config import Settings


logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


class MailDeliveryError(RuntimeError):
    pass


class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...

    def notify(self, *, to: str, subject: str, body: str) -> None: ...


def sender_address(settings: Settings) -> str:
    """The From address, resolved once for every backend.

    ``smtp_from``/``smtp_username`` are the fallbacks so a deploy that predates
    the HTTPS backend keeps its existing sender without renaming a variable.
    """
    return settings.mail_from or settings.smtp_from or settings.smtp_username


class _NotifyBySend:
    """Shared ``notify``: a best-effort send that never propagates failure."""

    def send(self, *, to: str, subject: str, body: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def notify(self, *, to: str, subject: str, body: str) -> None:
        try:
            self.send(to=to, subject=subject, body=body)
        except Exception:  # security notices never roll back completed state changes
            logger.exception("Security notification to %s failed", to)


class NullMailer(_NotifyBySend):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))
        logger.warning(
            "MAIL NOT CONFIGURED - would send to %s: %s\n%s", to, subject, body
        )


class ResendMailer(_NotifyBySend):
    """Delivery over Resend's HTTPS API.

    Required wherever outbound SMTP is blocked: Railway disables it below the
    Pro plan, so ``smtp.gmail.com:587`` fails with ``[Errno 101] Network is
    unreachable`` no matter how the credentials are set.
    """

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client

    def send(self, *, to: str, subject: str, body: str) -> None:
        http = self._client if self._client is not None else httpx.Client(timeout=10.0)
        try:
            response = http.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
                json={
                    "from": sender_address(self.settings),
                    "to": [to],
                    "subject": subject,
                    "text": body,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            # Callers turn this into a fixed "503 MAIL_UNAVAILABLE" body, so the
            # cause is recorded here or it is lost. Resend explains a refusal
            # (unverified domain, bad key) in the response body, not the status
            # line -- and the key rides a header, so it is never in either.
            failure = getattr(error, "response", None)
            detail = (
                f"{failure.status_code} {failure.text.strip()}"
                if failure is not None
                else str(error)
            )
            logger.warning(
                "Resend delivery to %s failed from %s: %s",
                to,
                sender_address(self.settings),
                detail,
            )
            raise MailDeliveryError(detail) from error
        finally:
            if self._client is None:
                http.close()


class SmtpMailer(_NotifyBySend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = sender_address(self.settings)
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        implicit_tls = self.settings.smtp_port == 465
        opener = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
        try:
            with opener(
                self.settings.smtp_host, self.settings.smtp_port, timeout=10
            ) as client:
                if self.settings.smtp_starttls and not implicit_tls:
                    client.starttls()
                if self.settings.smtp_username:
                    client.login(
                        self.settings.smtp_username, self.settings.smtp_password
                    )
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            # Callers turn this into a fixed "503 MAIL_UNAVAILABLE" body, so the
            # cause is recorded here or it is lost. Never log the password.
            logger.warning(
                "SMTP delivery to %s failed via %s:%s (starttls=%s, auth=%s): %s",
                to,
                self.settings.smtp_host,
                self.settings.smtp_port,
                self.settings.smtp_starttls,
                "on" if self.settings.smtp_username else "off",
                error,
            )
            raise MailDeliveryError(str(error)) from error


def mail_configured(settings: Settings) -> bool:
    return bool(settings.resend_api_key or settings.smtp_host)


def build_mailer(settings: Settings) -> Mailer:
    """Pick a backend. HTTPS wins over SMTP; setting the key is the opt-out."""
    if settings.resend_api_key:
        return ResendMailer(settings)
    if settings.smtp_host:
        return SmtpMailer(settings)
    return NullMailer()
