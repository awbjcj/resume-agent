from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.profile import Contact, Experience, ProfileFacts
from resume_agent.services.agents import CoverLetterBundle
from resume_agent.services.cover_letter_revision import revise_cover_letter_version
from resume_agent.tracking.repository import save_cover_letter, save_job
from resume_agent.tracking.tables import CoverLetter, Job


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self.content = content

    def run(self, prompt: str):
        self.seen = prompt
        return _Result(self.content)

    async def arun(self, prompt: str):
        return self.run(prompt)


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Engineer")],
    )


def _letter(provenance="exp1"):
    return CoverLetterContent(
        contact=Contact(name="Ada"),
        greeting="Hi",
        paragraphs=[CoverLetterParagraph(text="Body", provenance=[provenance])],
        closing="Bye",
    )


def test_revise_cover_letter_persists_lineage_and_fact_flag(monkeypatch):
    engine = make_engine("sqlite://")
    init_db(engine)
    exports = []
    monkeypatch.setattr(
        "resume_agent.services.cover_letter_revision.load_facts",
        lambda path: _facts(),
    )
    monkeypatch.setattr(
        "resume_agent.services.cover_letter_revision.export_job_artifacts",
        lambda session, job_id: exports.append(job_id),
    )

    with Session(engine) as session:
        job = save_job(session, Job(source="manual", jd_text="jd", company="Acme", title="Eng"))
        assert job.id is not None
        parent = save_cover_letter(
            session,
            CoverLetter(job_id=job.id, content_json=_letter().model_dump(mode="json")),
        )
        assert parent.id is not None
        bundle = CoverLetterBundle(
            draft=_Agent(_letter()),
            reviser=_Agent(_letter()),
            revision=_Agent(_letter(provenance="ghost")),
        )

        child = revise_cover_letter_version(session, parent.id, "warmer tone", bundle=bundle)

        assert child is not None
        assert child.origin == "revision"
        assert child.instruction == "warmer tone"
        assert child.parent_id == parent.id
        assert child.fact_check_passed is False
        assert exports == [job.id]
