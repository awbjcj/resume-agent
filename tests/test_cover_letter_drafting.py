from resume_agent.cover_letter.drafting import (
    compose_cover_letter_input,
    compose_revise_input,
    draft_cover_letter,
)
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, Experience, ProfileFacts


class _Result:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content
        self.prompt = ""

    def run(self, prompt):
        self.prompt = prompt
        return _Result(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Eng")],
    )


def test_compose_input_includes_profile_and_jd():
    text = compose_cover_letter_input("Build APIs", JobCriteria(), _facts())
    assert "Acme" in text and "Build APIs" in text


def test_draft_returns_typed_content():
    letter = CoverLetterContent(contact=Contact(name="Ada"), greeting="Hi", paragraphs=[], closing="Bye")
    agent = _FakeAgent(letter)
    out = draft_cover_letter("input", agent)
    assert isinstance(out, CoverLetterContent)


def test_revise_input_names_unsupported_ids():
    letter = CoverLetterContent(
        contact=Contact(name="Ada"),
        greeting="Hi",
        paragraphs=[CoverLetterParagraph(text="p", provenance=["GHOST"])],
        closing="Bye",
    )
    text = compose_revise_input(letter, ["GHOST"], _facts(), "Build APIs")
    assert "GHOST" in text
