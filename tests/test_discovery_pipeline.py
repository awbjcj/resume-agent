from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.pipeline import discover
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import JobCriteria, SponsorshipSignal
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.discovery.fit import FitScore
from resume_agent.tracking.repository import jobs_by_status
from resume_agent.tracking.tables import JobStatus


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
