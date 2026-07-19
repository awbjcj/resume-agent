from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_agent.services.agents import TailorBundle
from resume_agent.services.revision import revise_resume_version
from resume_agent.tracking.repository import save_job, save_resume_version
from resume_agent.tracking.tables import Job, ResumeVersion


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
        experience=[
            Experience(
                id="exp1",
                company="Acme",
                title="Engineer",
                bullets=[Bullet(id="b1", text="Built systems")],
            )
        ],
    )


def _content(provenance="b1"):
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="Acme",
                title="Engineer",
                provenance="exp1",
                bullets=[TailoredBullet(text="Built systems", provenance=provenance)],
            )
        ],
    )


def test_revise_resume_version_persists_lineage_and_fact_flag(monkeypatch):
    engine = make_engine("sqlite://")
    init_db(engine)
    exports = []
    monkeypatch.setattr(
        "resume_agent.services.revision.load_facts", lambda path: _facts()
    )
    monkeypatch.setattr(
        "resume_agent.services.revision.export_job_artifacts",
        lambda session, job_id: exports.append(job_id),
    )

    with Session(engine) as session:
        job = save_job(
            session, Job(source="manual", jd_text="jd", company="Acme", title="Eng")
        )
        assert job.id is not None
        parent = save_resume_version(
            session,
            ResumeVersion(
                job_id=job.id, round=1, content_json=_content().model_dump(mode="json")
            ),
        )
        assert parent.id is not None
        bundle = TailorBundle(
            tailor=_Agent(_content()),
            reviser=_Agent(_content()),
            reviewers={},
            revision=_Agent(_content(provenance="ghost")),
        )

        child = revise_resume_version(
            session, parent.id, "make it sharper", bundle=bundle
        )

        assert child is not None
        assert child.origin == "revision"
        assert child.instruction == "make it sharper"
        assert child.parent_version_id == parent.id
        assert child.fact_check_passed is False
        assert exports == [job.id]
