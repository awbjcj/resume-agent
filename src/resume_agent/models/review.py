from enum import Enum

from pydantic import Field

from resume_agent.models.base import ExtensibleModel


class Severity(str, Enum):
    blocking = "blocking"  # fact-check failures use this; gates the whole round
    major = "major"
    minor = "minor"


class ReviewIssue(ExtensibleModel):
    severity: Severity
    message: str
    suggestion: str | None = None
    location: str | None = None  # which section/bullet the issue refers to


class ReviewCritique(ExtensibleModel):
    """One reviewer agent's structured verdict on a ResumeContent draft."""

    reviewer: str  # the reviewing agent's name
    score: int = Field(ge=0, le=100)
    passed: bool  # the reviewer's pass/fail; fact-check's value is the hard gate
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str | None = None


class MergedPanelReview(ExtensibleModel):
    """One combined advisory call's critique for every configured dimension."""

    critiques: list[ReviewCritique] = Field(default_factory=list)
