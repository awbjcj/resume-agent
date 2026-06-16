from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.pipeline import discover, reextract
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import JobCriteria, Seniority, SponsorshipSignal
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.discovery.fit import FitScore
from resume_agent.tracking.repository import jobs_by_status, save_job
from resume_agent.tracking.tables import Job, JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _Result:
    def __init__(self, content):
        self.content = content


class _ExtractAgent:
    """Returns denied criteria when the JD mentions 'nosponsor', else offered."""

    def run(self, prompt):
        if "nosponsor" in prompt:
            return _Result(JobCriteria(sponsorship_signal=SponsorshipSignal.denied))
        return _Result(JobCriteria(sponsorship_signal=SponsorshipSignal.offered))


class _FitAgent:
    def run(self, prompt):
        return _Result(FitScore(score=90, rationale="great fit"))


class _ReextractAgent:
    def __init__(self, content):
        self._content = content
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return _Result(self._content)


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


def test_reextract_rewrites_criteria_without_changing_status():
    agent = _ReextractAgent(JobCriteria(seniority=Seniority.staff))
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                status=JobStatus.shortlisted.value,
                criteria_json={"seniority": None},
                fit_score=70,
            ),
        )
        save_job(
            s,
            Job(
                source="manual",
                jd_text="rejected-jd",
                status=JobStatus.rejected.value,
                criteria_json={"seniority": None},
            ),
        )
        save_job(
            s,
            Job(
                source="manual",
                jd_text="   ",
                status=JobStatus.filtered.value,
                criteria_json={"seniority": None},
            ),
        )
        save_job(s, Job(source="manual", jd_text="raw-jd", status=JobStatus.raw.value))

        updated = reextract(s, agent)

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        filtered = jobs_by_status(s, JobStatus.filtered.value)
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert updated == 2
        assert shortlisted[0].criteria_json["seniority"] == "staff"
        assert shortlisted[0].status == JobStatus.shortlisted.value
        assert shortlisted[0].fit_score == 70
        assert rejected[0].criteria_json["seniority"] == "staff"
        assert rejected[0].status == JobStatus.rejected.value
        assert filtered[0].criteria_json == {"seniority": None}
        assert raw and raw[0].criteria_json is None
        assert agent.prompts == ["rejected-jd", "jd"]
