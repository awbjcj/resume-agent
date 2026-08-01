"""Mock interview request and response schemas."""

from __future__ import annotations

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class InterviewStyleIn(CamelModel):
    stage: str = "hiring_manager"
    demeanor: str = "neutral"
    difficulty: str = "standard"
    question_count: int = Field(default=8, ge=4, le=12)
    extra: str = Field(default="", max_length=2_000)


class InterviewStartIn(CamelModel):
    job_id: int
    resume_version_id: int
    style: InterviewStyleIn = Field(default_factory=InterviewStyleIn)


class InterviewMessageIn(CamelModel):
    message: str = Field(min_length=1, max_length=100_000)


class InterviewTurnOut(CamelModel):
    role: str
    text: str
    question_id: str = ""
    is_followup: bool = False
    at: str = ""
    notice: str = ""


class PlanItemOut(CamelModel):
    id: str
    competency: str = ""
    question_type: str = ""
    status: str = "pending"


class QuestionReviewOut(CamelModel):
    question_id: str
    question: str = ""
    score: int = 0
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    suggested_answer: str = ""


class InterviewDebriefOut(CamelModel):
    summary: str = ""
    question_reviews: list[QuestionReviewOut] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    star_notes: str = ""


class InterviewProgressOut(CamelModel):
    asked: int = 0
    total: int = 0


class InterviewSessionOut(CamelModel):
    session_id: str
    job_id: int
    resume_version_id: int
    company: str = ""
    title: str = ""
    started_at: str
    ended_at: str | None = None
    status: str
    archived_at: str | None = None
    concluded: bool = False
    style: InterviewStyleIn
    progress: InterviewProgressOut
    plan: list[PlanItemOut] | None = None
    turns: list[InterviewTurnOut] = Field(default_factory=list)
    debrief: InterviewDebriefOut | None = None


class InterviewSessionSummaryOut(CamelModel):
    session_id: str
    job_id: int
    company: str = ""
    title: str = ""
    started_at: str
    ended_at: str | None = None
    status: str
    archived_at: str | None = None
    asked_count: int = 0
    question_count: int = 0
    overall_score: float | None = None


class InterviewSessionsOut(CamelModel):
    sessions: list[InterviewSessionSummaryOut] = Field(default_factory=list)
