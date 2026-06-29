import pytest
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
    def __init__(self):
        self.closed = False

    def run(self, prompt):
        return _Result(ResumeContent(contact=Contact(name="Ada")))

    async def arun(self, prompt):
        return self.run(prompt)

    async def aclose(self):
        self.closed = True


class _FactCheck:
    def __init__(self):
        self.closed = False

    def run(self, prompt):
        return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))

    async def arun(self, prompt):
        return self.run(prompt)

    async def aclose(self):
        self.closed = True


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
    tailor_agent = _ContentAgent()
    reviewer = _FactCheck()
    reviser_agent = _ContentAgent()
    with _session() as s:
        job = save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        versions = tailor_job(
            s,
            job,
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=tailor_agent,
            reviewer_agents={"fact-check": reviewer},
            reviser_agent=reviser_agent,
        )

        assert len(versions) == 1
        assert versions[0].fact_check_passed is True
        assert versions[0].round == 1
        assert versions[0].content_json is not None
        assert versions[0].content_json["contact"]["name"] == "Ada"

        stored = resume_versions_for_job(s, _require_id(job.id))
        assert len(stored) == 1
        assert job.status == JobStatus.tailored.value
    assert tailor_agent.closed is True
    assert reviewer.closed is True
    assert reviser_agent.closed is True


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
            Job(
                source="manual",
                jd_text="jd",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        results = tailor_jobs(
            s,
            [job],
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
            reporter=ProgressReporter("tailor", tmp_path),
        )

        assert list(results) == [_require_id(job.id)]
        assert len(results[_require_id(job.id)]) == 1
        rec = read_progress("tailor", tmp_path)
        assert rec is not None
        assert rec["state"] == "done"
        assert rec["total"] == 1


def test_tailor_jobs_runs_jobs_concurrently(monkeypatch):
    import asyncio
    import time

    monkeypatch.setenv("LLM_CONCURRENCY", "8")
    from resume_agent.config import get_settings

    get_settings.cache_clear()

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _SlowContent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            await asyncio.sleep(0.05)
            return _Result(ResumeContent(contact=Contact(name="Ada")))

    class _SlowFactCheck:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            await asyncio.sleep(0.05)
            return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))

    try:
        with _session() as s:
            jobs = [
                save_job(
                    s,
                    Job(
                        source="manual",
                        jd_text=f"jd{i}",
                        status=JobStatus.approved.value,
                        criteria_json=JobCriteria().model_dump(mode="json"),
                    ),
                )
                for i in range(4)
            ]
            t0 = time.perf_counter()
            results = tailor_jobs(
                s,
                jobs,
                ProfileFacts(contact=Contact(name="Ada")),
                config,
                tailor_agent=_SlowContent(),
                reviewer_agents={"fact-check": _SlowFactCheck()},
                reviser_agent=_SlowContent(),
            )
            elapsed = time.perf_counter() - t0
            assert len(results) == 4
        assert elapsed < 0.3
    finally:
        get_settings.cache_clear()


def test_tailor_jobs_isolates_a_failing_job():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    with _session() as s:
        ok_job = save_job(
            s,
            Job(
                source="manual",
                jd_text="ok",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        bad_job = save_job(
            s,
            Job(
                source="manual",
                jd_text="bad",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )

        class _Selective:
            def run(self, prompt):
                raise NotImplementedError

            async def arun(self, prompt):
                if "bad" in prompt:
                    raise RuntimeError("model down")
                return _Result(ResumeContent(contact=Contact(name="Ada")))

        results = tailor_jobs(
            s,
            [ok_job, bad_job],
            ProfileFacts(contact=Contact(name="Ada")),
            config,
            tailor_agent=_Selective(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_Selective(),
        )

        assert _require_id(ok_job.id) in results
        assert _require_id(bad_job.id) not in results
        assert ok_job.status == JobStatus.tailored.value
        assert bad_job.status == JobStatus.approved.value


def test_tailor_jobs_rejects_unpersisted_job_before_llm_work():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _NoCall:
        def run(self, prompt):
            raise AssertionError("LLM should not be called")

        async def arun(self, prompt):
            raise AssertionError("LLM should not be called")

    with _session() as s:
        job = Job(
            source="manual", jd_text="jd", status=JobStatus.approved.value,
            criteria_json=JobCriteria().model_dump(mode="json"),
        )
        with pytest.raises(ValueError):
            tailor_jobs(
                s,
                [job],
                ProfileFacts(contact=Contact(name="Ada")),
                config,
                tailor_agent=_NoCall(),
                reviewer_agents={"fact-check": _NoCall()},
                reviser_agent=_NoCall(),
            )
