import json

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.pipeline import (
    discover,
    reprocess,
    run_extract,
    run_relevance,
    run_score,
)
from resume_agent.discovery.relevance import RelevanceVerdict
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import (
    JobCriteriaExtract,
    SponsorshipSignal,
)
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.discovery.fit import FitLocation, FitScore
from resume_agent.tracking.repository import jobs_by_status, save_job
from resume_agent.tracking.tables import Job, JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _Result:
    def __init__(self, content):
        self.content = content


def _extract(**overrides) -> JobCriteriaExtract:
    base = dict(
        sponsorship_signal=SponsorshipSignal.offered,
        seniority=None,
        employment_type=None,
        tech_stack=[],
        industry=None,
        company_size=None,
        yoe_min=None,
        salary_range=None,
        remote_policy=None,
        location=None,
        must_have_skills=[],
        nice_to_have_skills=[],
    )
    base.update(overrides)
    return JobCriteriaExtract.model_validate(base)


class _ExtractAgent:
    """Returns denied criteria when the JD mentions 'nosponsor', else offered."""

    def run(self, prompt):
        if "nosponsor" in prompt:
            return _Result(_extract(sponsorship_signal=SponsorshipSignal.denied))
        return _Result(_extract(sponsorship_signal=SponsorshipSignal.offered))

    async def arun(self, prompt):
        return self.run(prompt)


class _FitAgent:
    def run(self, prompt):
        return _Result(FitScore(score=90, rationale="great fit"))

    async def arun(self, prompt):
        return self.run(prompt)


class _Judge:
    """Keeps titles containing 'engineer'; rejects others."""

    def run(self, prompt):
        keep = "JOB TITLE:\nAI Engineer" in prompt
        reason = "ok" if keep else "off-target"
        return _Result(RelevanceVerdict(keep=keep, reason=reason))

    async def arun(self, prompt):
        return self.run(prompt)


class _ReextractAgent:
    def __init__(self, content):
        self._content = content
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return _Result(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def test_run_relevance_rejects_offtarget_keeps_match():
    cfg = SearchConfig(target_role="AI engineering roles")
    with _session() as s:
        save_job(
            s,
            Job(source="x", jd_text="build systems", title="AI Engineer", status=JobStatus.raw.value),
        )
        save_job(
            s,
            Job(source="x", jd_text="drive a truck", title="CDL Driver", status=JobStatus.raw.value),
        )
        rejected_count = run_relevance(s, cfg, _Judge())
        assert rejected_count == 1
        raw = jobs_by_status(s, JobStatus.raw.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        reject_reason = rejected[0].reject_reason
        assert [j.title for j in raw] == ["AI Engineer"]
        assert reject_reason is not None
        assert reject_reason.startswith("off-target role")


def test_run_relevance_noop_when_no_target_and_no_titles():
    cfg = SearchConfig()
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd", title="Whatever", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, _Judge()) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_run_relevance_noop_when_titles_are_blank():
    cfg = SearchConfig(titles=["", "   "])
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd", title="Whatever", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, _Judge()) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_run_relevance_noop_when_agent_none():
    cfg = SearchConfig(target_role="AI roles")
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd", title="CDL Driver", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, None) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_run_relevance_keeps_job_on_agent_error():
    class _Boom:
        def run(self, prompt):
            raise RuntimeError("api down")

        async def arun(self, prompt):
            return self.run(prompt)

    cfg = SearchConfig(target_role="AI roles")
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd", title="CDL Driver", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, _Boom()) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_discover_extracts_filters_scores_and_shortlists():
    cfg = SearchConfig(sponsorship_required=True)
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="good role, will sponsor")
        add_job(s, source="manual", jd_text="bad role, nosponsor here")

        counts = discover(s, cfg, facts, _ExtractAgent(), _FitAgent())

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        assert len(shortlisted) == 1
        assert shortlisted[0].fit_score == 90
        assert shortlisted[0].criteria_json is not None
        assert shortlisted[0].criteria_json["sponsorship_signal"] == "offered"
        assert len(rejected) == 1
        assert rejected[0].reject_reason == "sponsorship not available"
        assert counts[JobStatus.shortlisted.value] == 1
        assert counts[JobStatus.rejected.value] == 1


def test_discover_reports_progress_done(tmp_path):
    from resume_agent.progress import ProgressReporter, read_progress

    cfg = SearchConfig(sponsorship_required=True)
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="good role, will sponsor")
        discover(
            s, cfg, facts, _ExtractAgent(), _FitAgent(),
            reporter=ProgressReporter("discover", tmp_path),
        )
    rec = read_progress("discover", tmp_path)
    assert rec is not None and rec["state"] == "done"


def test_run_score_reports_phase_three(tmp_path):
    from resume_agent.progress import ProgressReporter, read_progress

    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(source="x", jd_text="jd", title="Eng", status=JobStatus.filtered.value,
                criteria_json={}),
        )
        run_score(
            s, facts, _SicLocFitAgent(), aliases_path=tmp_path / "a.json",
            reporter=ProgressReporter("discover", tmp_path),
        )
    rec = read_progress("discover", tmp_path)
    assert rec is not None
    assert rec["phase_index"] == 3 and rec["phase_count"] == 3
    assert rec["current"] == 1 and rec["total"] == 1


def test_discover_commits_once_per_stage(monkeypatch):
    cfg = SearchConfig(sponsorship_required=True)
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="good role, will sponsor")
        add_job(s, source="manual", jd_text="another good role")

        commits = {"n": 0}
        real_commit = s.commit

        def _counting_commit():
            commits["n"] += 1
            return real_commit()

        monkeypatch.setattr(s, "commit", _counting_commit)
        discover(s, cfg, facts, _ExtractAgent(), _FitAgent())

    assert commits["n"] == 3



class _SicLocFitAgent:
    def run(self, prompt):
        return _Result(
            FitScore(
                score=88, rationale="ok", sic_major="73",
                location=FitLocation(city="Austin", region="TX", country="USA"),
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


def test_run_score_writes_sic_and_location_into_criteria(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng",
                status=JobStatus.filtered.value,
                criteria_json={"industry": "fintech", "location": "Austin, TX, USA"},
            ),
        )
        run_score(s, facts, _SicLocFitAgent(), aliases_path=tmp_path / "a.json")
        job = jobs_by_status(s, JobStatus.shortlisted.value)[0]
        assert job.fit_score == 88
        assert job.criteria_json is not None
        assert job.criteria_json["sic_major"] == "73"
        assert job.criteria_json["industry"] == "fintech"  # preserved
        assert job.criteria_json["location_parts"]["region"] == "TX"
        assert job.criteria_json["location_parts"]["is_us"] is True
        assert job.criteria_json["location_parts"]["raw"] == "Austin, TX, USA"


def test_run_score_refreshes_aliases_when_canonicalizer_given(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    path = tmp_path / "aliases.json"

    def canon(tokens):
        return {"k8s": "kubernetes"} if "k8s" in tokens else {t: t for t in tokens}

    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng",
                status=JobStatus.filtered.value,
                criteria_json={"must_have_skills": ["k8s"]},
            ),
        )
        run_score(s, facts, _SicLocFitAgent(), canonicalizer=canon, aliases_path=path)
        assert json.loads(path.read_text("utf-8"))["k8s"] == "kubernetes"


class _OneBadExtractAgent:
    """Raises a JSON parse error on the 'boom' JD, succeeds otherwise.

    Mirrors agno raising mid-parse when the model emits malformed JSON (e.g. a
    stray comma) for a single job.
    """

    def run(self, prompt):
        if "boom" in prompt:
            raise json.JSONDecodeError("Expecting ',' delimiter", prompt, 0)
        return _Result(_extract(sponsorship_signal=SponsorshipSignal.offered))

    async def arun(self, prompt):
        return self.run(prompt)


class _RawStrExtractAgent:
    """Returns a raw str for the 'boom' JD, tripping the isinstance type guard."""

    def run(self, prompt):
        if "boom" in prompt:
            return _Result("sorry, here is some prose instead of JSON")
        return _Result(_extract(sponsorship_signal=SponsorshipSignal.offered))

    async def arun(self, prompt):
        return self.run(prompt)


class _OneBadFitAgent:
    """Raises a JSON parse error scoring the 'boom' JD, succeeds otherwise."""

    def run(self, prompt):
        if "boom" in prompt:
            raise json.JSONDecodeError("Expecting ',' delimiter", prompt, 0)
        return _Result(FitScore(score=90, rationale="great fit"))

    async def arun(self, prompt):
        return self.run(prompt)


def test_run_extract_skips_failed_job_and_persists_the_rest():
    """One job with unparseable LLM output must not discard the whole stage."""
    with _session() as s:
        save_job(s, Job(source="x", jd_text="good role", title="A", status=JobStatus.raw.value))
        save_job(s, Job(source="x", jd_text="boom role", title="B", status=JobStatus.raw.value))

        run_extract(s, _OneBadExtractAgent())  # must not raise

        extracted = jobs_by_status(s, JobStatus.extracted.value)
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert [j.title for j in extracted] == ["A"]  # good job saved
        assert [j.title for j in raw] == ["B"]  # failed job left raw to retry


def test_run_extract_skips_job_when_agent_returns_wrong_type():
    """A raw-str fallback (isinstance guard -> TypeError) is also isolated."""
    with _session() as s:
        save_job(s, Job(source="x", jd_text="good role", title="A", status=JobStatus.raw.value))
        save_job(s, Job(source="x", jd_text="boom role", title="B", status=JobStatus.raw.value))

        run_extract(s, _RawStrExtractAgent())  # must not raise

        assert [j.title for j in jobs_by_status(s, JobStatus.extracted.value)] == ["A"]
        assert [j.title for j in jobs_by_status(s, JobStatus.raw.value)] == ["B"]


def test_run_score_skips_failed_job_and_persists_the_rest(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(source="x", jd_text="good", title="A", status=JobStatus.filtered.value,
                criteria_json={}),
        )
        save_job(
            s,
            Job(source="x", jd_text="boom", title="B", status=JobStatus.filtered.value,
                criteria_json={}),
        )

        run_score(s, facts, _OneBadFitAgent(), aliases_path=tmp_path / "a.json")  # must not raise

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        filtered = jobs_by_status(s, JobStatus.filtered.value)
        assert [j.title for j in shortlisted] == ["A"]  # good job scored + saved
        assert [j.title for j in filtered] == ["B"]  # failed job left filtered to retry


def test_discover_isolates_a_single_unparseable_job():
    """End-to-end: one bad job does not zero out the shortlist."""
    cfg = SearchConfig()
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="good role")
        add_job(s, source="manual", jd_text="boom role")

        counts = discover(s, cfg, facts, _OneBadExtractAgent(), _FitAgent())

        assert counts.get(JobStatus.shortlisted.value, 0) == 1
        assert counts.get(JobStatus.raw.value, 0) == 1  # bad job parked for retry



def test_filter_and_relevance_set_reject_category():
    cfg = SearchConfig(sponsorship_required=True, target_role="AI engineering roles")
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="bad role, nosponsor here", title="AI Engineer")
        add_job(s, source="manual", jd_text="drive a truck", title="CDL Driver")
        discover(s, cfg, facts, _ExtractAgent(), _FitAgent(), _Judge())
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        categories = {j.reject_category for j in rejected}
        assert categories == {"filtered", "relevance"}


def test_reprocess_shortlisted_rescores_and_skips_progress():
    cfg = SearchConfig()  # no relevance target -> relevance gate is a no-op
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd a", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=10, criteria_json={}))
        save_job(s, Job(source="x", jd_text="jd b", title="Eng",
                        status=JobStatus.tailored.value, fit_score=10, criteria_json={}))

        counts = reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["shortlisted"])

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        tailored = jobs_by_status(s, JobStatus.tailored.value)
        assert shortlisted[0].fit_score == 90       # re-scored
        assert tailored[0].fit_score == 10           # progress-guarded, untouched
        assert counts[JobStatus.shortlisted.value] == 1


def test_reprocess_rejected_relevance_only():
    cfg = SearchConfig()
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd r", title="Eng",
                        status=JobStatus.rejected.value, reject_category="relevance"))
        save_job(s, Job(source="x", jd_text="jd f", title="Eng",
                        status=JobStatus.rejected.value, reject_category="filtered"))

        reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["rejected:relevance"])

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        assert len(shortlisted) == 1
        assert {j.reject_category for j in rejected} == {"filtered"}


def test_reprocess_unknown_scope_raises():
    import pytest
    with _session() as s:
        with pytest.raises(ValueError):
            reprocess(s, SearchConfig(), ProfileFacts(contact=Contact(name="Ada")),
                      _ExtractAgent(), _FitAgent(), ["bogus"])


def test_reprocess_only_touches_scoped_jobs():
    cfg = SearchConfig()
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd s", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=10, criteria_json={}))
        save_job(s, Job(source="x", jd_text="jd raw", title="Eng", status=JobStatus.raw.value))

        reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["shortlisted"])

        raw = jobs_by_status(s, JobStatus.raw.value)
        assert [j.jd_text for j in raw] == ["jd raw"]
        assert raw[0].criteria_json is None


def test_reprocess_empty_scope_processes_nothing():
    cfg = SearchConfig()
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd raw", title="Eng", status=JobStatus.raw.value))
        reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["shortlisted"])
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1
        assert not jobs_by_status(s, JobStatus.shortlisted.value)


def test_reprocess_clears_stale_fit_when_now_rejected():
    cfg = SearchConfig(sponsorship_required=True)
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="bad role, nosponsor here", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=88,
                        fit_rationale="old rationale", criteria_json={"stale": 1}))

        reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["shortlisted"])

        rejected = jobs_by_status(s, JobStatus.rejected.value)
        assert len(rejected) == 1
        assert rejected[0].fit_score is None
        assert rejected[0].fit_rationale is None
        assert rejected[0].reject_category == "filtered"
