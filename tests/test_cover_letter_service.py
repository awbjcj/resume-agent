from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.cover_letter.service import generate_cover_letter
from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_tailor_harness.models.profile import Contact, Experience, ProfileFacts


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Eng")],
    )


def _letter(prov):
    return CoverLetterContent(
        contact=Contact(name="Ada"),
        greeting="Hi",
        paragraphs=[CoverLetterParagraph(text="p", provenance=[prov])],
        closing="Bye",
    )


class _Result:
    def __init__(self, c):
        self.content = c


class _Agent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _Result(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def test_generate_revises_until_provenance_clean_then_persists():
    draft_agent = _Agent(_letter("GHOST"))
    reviser_agent = _Agent(_letter("exp1"))
    with _session() as s:
        job = add_job(
            s, source="manual", jd_text="Build APIs", company="Acme", title="Eng"
        )
        assert job is not None
        cover = generate_cover_letter(
            s, job, _facts(), draft_agent, reviser_agent, max_rounds=2
        )
        assert cover.id is not None
        assert cover.fact_check_passed is True
        assert cover.content_json is not None
        assert cover.content_json["paragraphs"][0]["provenance"] == ["exp1"]


def test_generate_marks_unfixed_fabrication_as_failed():
    draft_agent = _Agent(_letter("GHOST"))
    reviser_agent = _Agent(_letter("STILL_BAD"))
    with _session() as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        assert job is not None
        cover = generate_cover_letter(
            s, job, _facts(), draft_agent, reviser_agent, max_rounds=2
        )
        assert cover.fact_check_passed is False
