import base64
from dataclasses import dataclass

from resume_tailor_harness.discovery.connectors.text import html_to_text
from resume_tailor_harness.gmail.auth import (  # noqa: F401 — CLI compat re-export
    build_gmail_service_interactive as build_gmail_service,
)

BODY_CHAR_LIMIT = 4000


@dataclass
class EmailMessage:
    """The minimal email shape the matcher/classifier need."""

    sender: str
    sender_domain: str
    subject: str
    snippet: str
    thread_id: str | None = None
    message_id: str | None = None
    body: str | None = None


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _walk_parts(payload: dict):
    yield payload
    for part in payload.get("parts") or []:
        yield from _walk_parts(part)


def extract_body(payload: dict) -> str:
    """text/plain part preferred, else html→text; truncated for classification."""
    html = ""
    for part in _walk_parts(payload):
        data = (part.get("body") or {}).get("data") or ""
        if not data:
            continue
        if part.get("mimeType") == "text/plain":
            return _decode(data)[:BODY_CHAR_LIMIT].strip()
        if part.get("mimeType") == "text/html" and not html:
            html = _decode(data)
    return html_to_text(html)[:BODY_CHAR_LIMIT].strip() if html else ""


def fetch_message_body(service, message_id: str) -> str:
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    return extract_body(msg.get("payload", {}))


def _header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _domain(sender: str) -> str:
    if "@" not in sender:
        return ""
    return sender.split("@", 1)[1].rstrip(">").strip().lower()


def fetch_recent_messages(service, max_results: int = 50) -> list[EmailMessage]:
    """Fetch recent inbox messages as EmailMessages (read-only)."""
    listing = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, labelIds=["INBOX"])
        .execute()
    )
    messages: list[EmailMessage] = []
    for ref in listing.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        sender = _header(headers, "From")
        messages.append(
            EmailMessage(
                sender=sender,
                sender_domain=_domain(sender),
                subject=_header(headers, "Subject"),
                snippet=msg.get("snippet", ""),
                thread_id=msg.get("threadId"),
                message_id=ref["id"],
            )
        )
    return messages
