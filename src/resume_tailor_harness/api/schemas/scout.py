"""Discovery Scout request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, Field

from resume_tailor_harness.api.schemas.base import CamelModel


class ScoutMessageIn(CamelModel):
    message: str = Field(min_length=1, max_length=2_000)


class ScoutDismissIn(CamelModel):
    reason: str = Field(default="", max_length=200)


class ScoutApproveIn(CamelModel):
    manual_confirmation: bool = False


class ScoutResolveSourceIn(CamelModel):
    url: AnyHttpUrl = Field(max_length=2_048)


class ScoutCitationOut(CamelModel):
    url: str
    title: str = ""


class ScoutSourceOut(CamelModel):
    company: str
    url: str = ""
    requested_url: str = ""
    canonical_board_url: str = ""
    ats: str | None = None
    token: str | None = None
    role_count: int | None = None
    error_code: str | None = None
    resolution_status: (
        Literal["verified", "unverified", "conflict", "failed"] | None
    ) = None
    resolution_reason: str = ""
    evidence: list["ScoutEvidenceOut"] = Field(default_factory=list)
    searched_families: list[str] = Field(default_factory=list)
    unsearched_families: list[str] = Field(default_factory=list)
    company_intelligence_status: Literal["ready", "stale", "missing"] | None = None
    company_intelligence_version: int | None = None


class ScoutEvidenceOut(CamelModel):
    kind: str
    source_url: str
    target_url: str = ""
    summary: str = ""


class ScoutManualConfirmationOut(CamelModel):
    company: str
    url: str
    ats: str | None = None
    resolution_reason: str
    confirmed_at: str


class ScoutTermOut(CamelModel):
    value: str
    term_kind: Literal[
        "keyword",
        "title",
        "role_anchor",
        "exclude_term",
        "location",
        "seniority",
        "adjacent_role",
    ]


class ScoutProposalOut(CamelModel):
    id: str
    kind: Literal["source", "search_term"]
    source: ScoutSourceOut | None = None
    term: ScoutTermOut | None = None
    reason: str = ""
    fit_score: int | None = None
    citations: list[ScoutCitationOut] = Field(default_factory=list)
    check: Literal[
        "validated", "unverified", "conflict", "failed", "duplicate", "avoid", "new"
    ]
    check_error: str = ""
    status: Literal["pending", "added", "dismissed"]
    dismiss_reason: str = ""
    resolved_at: str | None = None
    manual_confirmation: ScoutManualConfirmationOut | None = None


class ScoutTurnOut(CamelModel):
    role: Literal["scout", "user"]
    kind: Literal["reply", "recap", ""] = ""
    text: str
    at: str = ""
    notice: str = ""
    proposal_ids: list[str] = Field(default_factory=list)


class ScoutSessionOut(CamelModel):
    session_id: str
    session_title: str | None = None
    started_at: str
    ended_at: str | None = None
    status: Literal["active", "ended"]
    archived_at: str | None = None
    goal: str
    turns: list[ScoutTurnOut] = Field(default_factory=list)
    proposals: list[ScoutProposalOut] = Field(default_factory=list)
    recap: str | None = None
    scrape_available: bool
    scrape_unavailable_reason: str | None = None


class ScoutSessionSummaryOut(CamelModel):
    session_id: str
    session_title: str | None = None
    started_at: str
    ended_at: str | None = None
    status: Literal["active", "ended"]
    archived_at: str | None = None
    goal: str
    proposal_count: int = 0
    pending_count: int = 0
    added_count: int = 0
    dismissed_count: int = 0


class ScoutSessionsOut(CamelModel):
    sessions: list[ScoutSessionSummaryOut] = Field(default_factory=list)


class ScoutSessionPatchIn(CamelModel):
    title: str = Field(min_length=1, max_length=120)
