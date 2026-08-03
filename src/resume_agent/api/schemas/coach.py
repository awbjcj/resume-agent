"""Profile Coach request and response schemas."""

from __future__ import annotations

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class CoachResearchActionOut(CamelModel):
    kind: str
    target: str
    why: str = ""


class CoachTurnOut(CamelModel):
    role: str
    kind: str = ""
    text: str
    topic_id: str = ""
    at: str = ""
    notice: str = ""
    research_actions: list[CoachResearchActionOut] = Field(default_factory=list)


class CoachTopicOut(CamelModel):
    id: str
    gap: str = ""
    why_it_matters: str = ""
    related_ref: str = ""
    status: str = "open"
    note_doc_id: str | None = None


class CoachDraftNoteOut(CamelModel):
    topic_id: str
    title: str = ""
    summary: str = ""
    quotes: list[str] = Field(default_factory=list)
    status: str = "pending"


class CoachMetricGainOut(CamelModel):
    experience_id: str
    before: int
    after: int


class CoachSkillGainOut(CamelModel):
    skill: str
    before: int
    after: int


class CoachImpactOut(CamelModel):
    new_fact_ids: list[str] = Field(default_factory=list)
    bullets_gained_metrics: list[CoachMetricGainOut] = Field(default_factory=list)
    skills_gained_evidence: list[CoachSkillGainOut] = Field(default_factory=list)
    new_skills: list[str] = Field(default_factory=list)
    error: str | None = None


class CoachSessionOut(CamelModel):
    session_id: str
    session_title: str | None = None
    started_at: str
    ended_at: str | None = None
    status: str
    archived_at: str | None = None
    turns: list[CoachTurnOut] = Field(default_factory=list)
    topics: list[CoachTopicOut] = Field(default_factory=list)
    draft_notes: list[CoachDraftNoteOut] = Field(default_factory=list)
    recap: str | None = None
    impact: CoachImpactOut | None = None


class CoachSessionSummaryOut(CamelModel):
    session_id: str
    session_title: str | None = None
    started_at: str
    ended_at: str | None = None
    status: str
    archived_at: str | None = None
    topic_count: int = 0
    saved_note_count: int = 0


class CoachSessionsOut(CamelModel):
    sessions: list[CoachSessionSummaryOut] = Field(default_factory=list)


class CoachSessionPatchIn(CamelModel):
    title: str = Field(min_length=1, max_length=120)


class CoachMessageIn(CamelModel):
    message: str = Field(min_length=1, max_length=100_000)


class CoachNoteIn(CamelModel):
    title: str = Field(default="", max_length=200)
    summary: str = Field(min_length=1, max_length=100_000)
    quotes: list[str] = Field(min_length=1, max_length=20)


class CoachNoteOut(CamelModel):
    doc_id: str


class CoachEndIn(CamelModel):
    build: bool = True
