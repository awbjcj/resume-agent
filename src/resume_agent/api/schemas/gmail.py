from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class GmailConnectOut(CamelModel):
    auth_url: str


class GmailStatusOut(CamelModel):
    connected: bool
    scopes: list[str] = []
    draft_capable: bool = False
    client_source: str = "platform"  # "platform" | "own"
