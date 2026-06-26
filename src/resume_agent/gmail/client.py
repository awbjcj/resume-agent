from dataclasses import dataclass
from pathlib import Path

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_PATH = "config/gmail_credentials.json"
TOKEN_PATH = "data/gmail_token.json"


@dataclass
class EmailMessage:
    """The minimal email shape the matcher/classifier need."""

    sender: str
    sender_domain: str
    subject: str
    snippet: str
    thread_id: str | None = None
    message_id: str | None = None


def build_gmail_service(credentials_path: str = CREDENTIALS_PATH, token_path: str = TOKEN_PATH):
    """Build an authenticated, read-only Gmail service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


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
