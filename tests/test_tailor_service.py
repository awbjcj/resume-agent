from dataclasses import asdict

import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.models.job import JobCriteria
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.models.review import ReviewCritique
from resume_tailor_harness.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_tailor_harness.tailor.service import tailor_job, tailor_jobs
from resume_tailor_harness.taxonomy.clusters import ClusterMap
from resume_tailor_harness.taxonomy.snapshot import EffectiveTaxonomy
from resume_tailor_harness.tracking.repository import resume_versions_for_job, save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


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
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"js": "javascript"}))
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
            taxonomy=taxonomy,
        )

        assert len(versions) == 1
        assert versions[0].fact_check_passed is True
        assert versions[0].round == 1
        assert versions[0].content_json is not None
        assert versions[0].content_json["contact"]["name"] == "Ada"
        # Recorded from THIS round's config, not read back from current
        # settings later - see test_apply_gate_names_does_not_relabel_*.
        assert versions[0].gate_reviewers_json == ["fact-check"]
        assert versions[0].taxonomy_revision == taxonomy.semantic_revision
        assert versions[0].taxonomy_manifest_json == asdict(taxonomy.manifest)

        stored = resume_versions_for_job(s, _require_id(job.id))
        assert len(stored) == 1
        assert job.status == JobStatus.tailored.value
    assert tailor_agent.closed is True
    assert reviewer.closed is True
    assert reviser_agent.closed is True


def test_tailor_job_persists_the_frozen_fallback_portfolio():
    config = ReviewConfig(
        max_rounds=1,
        evidence_portfolio_enabled=True,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as session:
        job = save_job(
            session,
            Job(
                source="manual",
                jd_text="jd",
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        versions = tailor_job(
            session,
            job,
            ProfileFacts(contact=Contact(name="Ada")),
            config,
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )
        assert versions[0].evidence_portfolio_status == "deterministic_fallback"
        assert versions[0].evidence_portfolio_json is not None
        assert (
            versions[0]
            .evidence_portfolio_json["warning"]
            .startswith("Evidence planner unavailable")
        )


def test_tailor_jobs_reports_progress_and_returns_per_job(tmp_path):
    from resume_tailor_harness.progress import ProgressReporter, read_progress

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
        outcome = tailor_jobs(
            s,
            [job],
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
            reporter=ProgressReporter("tailor", tmp_path),
        )

        assert list(outcome.versions) == [_require_id(job.id)]
        assert len(outcome.versions[_require_id(job.id)]) == 1
        rec = read_progress("tailor", tmp_path)
        assert rec is not None
        assert rec["state"] == "done"
        assert rec["total"] == 1


def test_tailor_jobs_runs_jobs_concurrently(monkeypatch):
    import asyncio
    import time

    monkeypatch.setenv("LLM_CONCURRENCY", "8")
    from resume_tailor_harness.config import env_settings

    env_settings.cache_clear()

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
            return _Result(
                ReviewCritique(reviewer="fact-check", score=100, passed=True)
            )

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
            outcome = tailor_jobs(
                s,
                jobs,
                ProfileFacts(contact=Contact(name="Ada")),
                config,
                tailor_agent=_SlowContent(),
                reviewer_agents={"fact-check": _SlowFactCheck()},
                reviser_agent=_SlowContent(),
            )
            elapsed = time.perf_counter() - t0
            assert len(outcome.versions) == 4
        assert elapsed < 0.3
    finally:
        env_settings.cache_clear()


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

        outcome = tailor_jobs(
            s,
            [ok_job, bad_job],
            ProfileFacts(contact=Contact(name="Ada")),
            config,
            tailor_agent=_Selective(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_Selective(),
        )

        assert _require_id(ok_job.id) in outcome.versions
        assert _require_id(bad_job.id) not in outcome.versions
        assert _require_id(bad_job.id) in outcome.failures
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
            source="manual",
            jd_text="jd",
            status=JobStatus.approved.value,
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


def test_retailoring_a_rendered_job_keeps_it_rendered():
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
                status=JobStatus.rendered.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        tailor_job(
            s,
            job,
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        assert job.status == JobStatus.rendered.value


def test_retailoring_appends_a_new_attempt_and_keeps_old_versions():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    facts = ProfileFacts(contact=Contact(name="Ada"))
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
        first = tailor_job(
            s,
            job,
            facts,
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )
        second = tailor_job(
            s,
            job,
            facts,
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        assert first[0].attempt == 1
        assert second[0].attempt == 2
        stored = resume_versions_for_job(s, _require_id(job.id))
        assert len(stored) == 2  # nothing was replaced


class _ExplodingAgent:
    def __init__(self, message: str = "model is not configured"):
        self.message = message
        self.closed = False

    def run(self, prompt):
        raise ValueError(self.message)

    async def arun(self, prompt):
        return self.run(prompt)

    async def aclose(self):
        self.closed = True


def test_tailor_jobs_reports_the_failure_cause():
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
        outcome = tailor_jobs(
            s,
            [job],
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ExplodingAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        job_id = _require_id(job.id)
        assert outcome.versions == {}
        failure = outcome.failures[job_id]
        assert failure.error_type == "ValueError"
        assert "model is not configured" in failure.message
        assert "ValueError" in failure.traceback_tail
        # The job is left where it was so the next run retries it.
        assert job.status == JobStatus.approved.value


def test_tailor_jobs_keeps_successful_siblings_when_one_fails():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        good = save_job(
            s,
            Job(
                source="manual",
                jd_text="ok",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        outcome = tailor_jobs(
            s,
            [good],
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        assert list(outcome.versions) == [_require_id(good.id)]
        assert outcome.failures == {}
