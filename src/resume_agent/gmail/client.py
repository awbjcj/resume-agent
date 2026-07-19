from dataclasses import dataclass

from resume_agent.gmail.auth import (  # noqa: F401 — CLI compat re-export
    build_gmail_service_interactive as build_gmail_service,
)


@dataclass
class EmailMessage:
    """The minimal email shape the matcher/classifier need."""

    sender: str
    sender_domain: str
    subject: str
    snippet: str
    thread_id: str | None = None
    message_id: str | None = None


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
    listing = service.users().messages().list(
        userId="me", maxResults=max_results, labelIds=["INBOX"]
    ).execute()
    messages: list[EmailMessage] = []
    for ref in listing.get("messages", []):
        msg = service.users().messages().get(
            userId="me",
            id=ref["id"],
            format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
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
