import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from resume_agent.config import Settings


logger = logging.getLogger(__name__)


class MailDeliveryError(RuntimeError):
    pass


class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...

    def notify(self, *, to: str, subject: str, body: str) -> None: ...


class NullMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))
        logger.warning("MAIL NOT CONFIGURED - would send to %s: %s\n%s", to, subject, body)

    def notify(self, *, to: str, subject: str, body: str) -> None:
        self.send(to=to, subject=subject, body=body)


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from or self.settings.smtp_username
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        implicit_tls = self.settings.smtp_port == 465
        opener = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
        try:
            with opener(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as client:
                if self.settings.smtp_starttls and not implicit_tls:
                    client.starttls()
                if self.settings.smtp_username:
                    client.login(self.settings.smtp_username, self.settings.smtp_password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise MailDeliveryError(str(error)) from error

    def notify(self, *, to: str, subject: str, body: str) -> None:
        try:
            self.send(to=to, subject=subject, body=body)
        except Exception:  # security notices never roll back completed state changes
            logger.exception("Security notification to %s failed", to)


def mail_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host)


def build_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(settings) if mail_configured(settings) else NullMailer()
