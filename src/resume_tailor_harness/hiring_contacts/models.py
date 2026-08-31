"""Typed hiring-contact research artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel

HiringContactType = Literal[
    "recruiter",
    "hiring_manager",
    "team_leader",
    "team_member",
    "executive",
    "other",
]
HiringContactVerification = Literal["corroborated", "single_source"]


class HiringContactDraft(ExtensibleModel):
    name: str = ""
    public_role: str = ""
    contact_type: HiringContactType = "other"
    source_urls: list[str] = Field(default_factory=list)
    why_relevant: str = ""
    email_draft: str = ""
    short_message_draft: str = ""


class HiringContact(HiringContactDraft):
    verification_state: HiringContactVerification = "single_source"


class HiringContactIntelligenceDraft(ExtensibleModel):
    contacts: list[HiringContactDraft] = Field(default_factory=list)
    generic_email_draft: str = ""
    generic_short_message_draft: str = ""


class HiringContactIntelligence(ExtensibleModel):
    schema_version: int = 1
    job_id: int
    company: str
    title: str
    retrieved_at: datetime
    contacts: list[HiringContact] = Field(default_factory=list)
    generic_email_draft: str
    generic_short_message_draft: str
    caveat: str
