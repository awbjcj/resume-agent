from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.service import tailor_job, tailor_jobs
from resume_agent.tracking.repository import resume_versions_for_job, save_job
from resume_agent.tracking.tables import Job, JobStatus


class _Result:
    def __init__(self, content):
        self.content = content


class _ContentAgent:
    def run(self, prompt):
        return _Result(ResumeContent(contact=Contact(name="Ada")))

    async def arun(self, prompt):
        return self.run(prompt)


class _FactCheck:
    def run(self, prompt):
        return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))

    async def arun(self, prompt):
        return self.run(prompt)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def test_tailor_job_persists_versions_and_marks_tailored():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        job = save_job(
            s,
            Job(source="manual", jd_text="jd", status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json")),
        )
        versions = tailor_job(
            s, job, ProfileFacts(contact=Contact(name="Ada")), config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(), reviewer_agents={"fact-check": _FactCheck()}, reviser_agent=_ContentAgent(),
        )

        assert len(versions) == 1
        assert versions[0].fact_check_passed is True
        assert versions[0].round == 1
        assert versions[0].content_json is not None
        assert versions[0].content_json["contact"]["name"] == "Ada"

        stored = resume_versions_for_job(s, _require_id(job.id))
        assert len(stored) == 1
        assert job.status == JobStatus.tailored.value


def test_tailor_jobs_reports_progress_and_returns_per_job(tmp_path):
    from resume_agent.progress import ProgressReporter, read_progress

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        job = save_job(
            s,
            Job(source="manual", jd_text="jd", status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json")),
        )
        results = tailor_jobs(
            s, [job], ProfileFacts(contact=Contact(name="Ada")), config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(), reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(), reporter=ProgressReporter("tailor", tmp_path),
        )

        assert list(results) == [_require_id(job.id)]
        assert len(results[_require_id(job.id)]) == 1
        rec = read_progress("tailor", tmp_path)
        assert rec is not None
        assert rec["state"] == "done"
        assert rec["total"] == 1
