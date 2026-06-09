import pytest

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue
from resume_agent.tailor.tailoring import (
    compose_revise_input,
    compose_tailor_input,
    revise,
    tailor,
)


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _Result(self._content)


def _facts():
    return ProfileFacts(contact=Contact(name="Ada Lovelace"))


def test_compose_tailor_input_includes_profile_criteria_jd():
    text = compose_tailor_input("Backend role", JobCriteria(), _facts())
    assert "Ada Lovelace" in text
    assert "Backend role" in text


def test_tailor_returns_resume_content():
    rc = ResumeContent(contact=Contact(name="Ada"))
    agent = _Agent(rc)
    assert tailor("input", agent) is rc
    assert agent.received == "input"


def test_tailor_rejects_wrong_type():
    with pytest.raises(TypeError):
        tailor("x", _Agent("nope"))


def test_compose_revise_input_includes_issue_messages():
    rc = ResumeContent(contact=Contact(name="Ada"))
    critiques = [
        ReviewCritique(
            reviewer="ats-keyword",
            score=70,
            passed=False,
            issues=[ReviewIssue(severity="major", message="Missing keyword: Kubernetes", suggestion="Add it if true")],
        )
    ]
    text = compose_revise_input(rc, critiques, _facts())
    assert "Missing keyword: Kubernetes" in text
    assert "Add it if true" in text


def test_revise_returns_resume_content():
    rc = ResumeContent(contact=Contact(name="Ada"))
    assert revise("input", _Agent(rc)) is rc
