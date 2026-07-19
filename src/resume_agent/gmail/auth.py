"""Tenant-aware Gmail credential storage + service construction.

Tokens are per-user workspace files (never DB rows). The interactive
InstalledAppFlow survives for the local CLI only; the web flow lives in
api/routers/gmail.py. Google SDK imports stay lazy so the offline test
suite never needs them on the import path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from resume_agent.gmail.errors import GmailNotConnected
from resume_agent.tenancy.context import current_context

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SCOPES = [SCOPE_READONLY, SCOPE_COMPOSE]
CREDENTIALS_PATH = "config/gmail_credentials.json"
_LEGACY_TOKEN_PATH = Path("data/gmail_token.json")


def token_path(data_dir: Path | None = None) -> Path:
    """Active workspace token, else <data_dir>/gmail_token.json, else legacy."""
    context = current_context()
    if context is not None:
        return context.paths.gmail_token
    if data_dir is not None:
        return Path(data_dir) / "gmail_token.json"
    return _LEGACY_TOKEN_PATH


def save_token_json(raw: str, data_dir: Path | None = None) -> Path:
    path = token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return path


def delete_token(data_dir: Path | None = None) -> bool:
    path = token_path(data_dir)
    if not path.is_file():
        return False
    path.unlink()
    return True


def load_credentials(data_dir: Path | None = None) -> Any | None:
    """Token file -> Credentials; refresh+persist if expired; None if absent/revoked."""
    path = token_path(data_dir)
    if not path.is_file():
        return None
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    try:
        creds = Credentials.from_authorized_user_file(str(path))
    except ValueError:
        return None
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            return None
        path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    return None


def granted_scopes(creds: Any) -> list[str]:
    return list(creds.scopes or [])


def has_compose(creds: Any) -> bool:
    return SCOPE_COMPOSE in granted_scopes(creds)


def build_service(data_dir: Path | None = None) -> Any:
    """Authenticated Gmail service for the active tenant, or GmailNotConnected."""
    creds = load_credentials(data_dir)
    if creds is None:
        raise GmailNotConnected("Gmail is not connected for this workspace")
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)


def build_gmail_service_interactive(credentials_path: str = CREDENTIALS_PATH) -> Any:
    """CLI-only: reuse a stored token, else run the local-browser consent flow."""
    creds = load_credentials()
    if creds is None:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        save_token_json(creds.to_json())
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)
