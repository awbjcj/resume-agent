from resume_agent.discovery.connectors.base import Connector, FetchResult, RawJob
from resume_agent.discovery.search_config import SearchConfig


def test_rawjob_carries_its_own_source():
    job = RawJob(
        source="greenhouse",
        url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme",
        title="Backend Engineer",
        location="Remote",
        jd_text="We are hiring.",
    )
    assert job.source == "greenhouse"
    assert job.jd_text == "We are hiring."


def test_connector_protocol_accepts_a_conforming_object():
    class _Fake:
        name = "fake"

        def fetch(self, search, limit=None):
            return FetchResult(jobs=[RawJob("fake", None, "Acme", "Eng", None, "jd")])

    fake: Connector = _Fake()
    result = fake.fetch(SearchConfig())
    assert result.jobs[0].source == "fake"
