"""Profile document + build wire schemas."""

from __future__ import annotations

from pydantic import AnyHttpUrl, Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.profile.corpus import SourceMode, SourceOrigin


class DocumentOut(CamelModel):
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str


class SourceOut(CamelModel):
    id: str
    filename: str
    mode: SourceMode
    primary: bool
    anchor: str | None = None
    added_at: str
    fragment_status: str
    origin: SourceOrigin = "upload"


class SourcePatch(CamelModel):
    mode: SourceMode | None = None
    anchor: str | None = None
    primary: bool | None = None


class SkeletonEntryOut(CamelModel):
    id: str
    kind: str
    label: str


class NoteIn(CamelModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=100_000)


class UrlIn(CamelModel):
    url: AnyHttpUrl


class MatrixRowOut(CamelModel):
    key: str
    display: str
    category: str | None = None
    group: str | None = None
    inferred: bool = False
    strength: float = 0.0
    last_used: str | None = None


class SkillGroupOut(CamelModel):
    slug: str
    label: str


class MatrixOut(CamelModel):
    generated_at: str = ""
    groups: list[SkillGroupOut] = Field(default_factory=list)
    rows: list[MatrixRowOut] = Field(default_factory=list)


class InterviewQuestionOut(CamelModel):
    id: str
    gap: str = ""
    why_it_matters: str = ""
    question_text: str
    related_ref: str = ""


class InterviewResearchActionOut(CamelModel):
    kind: str
    target: str
    why: str = ""


class InterviewHistoryAnswerOut(CamelModel):
    question_id: str
    doc_id: str
    answer_text: str


class InterviewHistoryRoundOut(CamelModel):
    round_id: str
    asked_at: str
    questions: list[InterviewQuestionOut] = Field(default_factory=list)
    research_actions: list[InterviewResearchActionOut] = Field(default_factory=list)
    answers: list[InterviewHistoryAnswerOut] = Field(default_factory=list)
    submitted_at: str | None = None


class InterviewHistoryOut(CamelModel):
    rounds: list[InterviewHistoryRoundOut] = Field(default_factory=list)


class InterviewAnswerIn(CamelModel):
    question_id: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=100_000)


class InterviewAnswersIn(CamelModel):
    answers: list[InterviewAnswerIn] = Field(default_factory=list, max_length=8)
    build: bool = True


class InterviewAnswersOut(CamelModel):
    doc_ids: list[str]
    build_started: bool
    build_run_id: str | None = None
    build_skipped_reason: str | None = None
