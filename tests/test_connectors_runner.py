from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.runner import run_pull
from resume_agent.discovery.connectors.telemetry import read_runs
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.tracking.repository import jobs_by_status, save_job
from resume_agent.tracking.tables import Job, JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _Good:
    name = "greenhouse"

    def fetch(self, search, limit=None):
        return [RawJob("greenhouse", "https://gh/1", "Acme", "Backend Engineer", "Remote", "jd a")]


class _Boom:
    name = "adzuna"

    def fetch(self, search, limit=None):
        raise RuntimeError("HTTP 429")


def test_run_pull_ingests_counts_and_isolates_failures(tmp_path):
    telemetry = tmp_path / "runs.json"
    with _session() as s:
        counts = run_pull(s, [_Good(), _Boom()], SearchConfig(), telemetry, limit=None)

        assert counts == {"greenhouse": 1}
        assert {j.source for j in jobs_by_status(s, JobStatus.raw.value)} == {"greenhouse"}

        runs = read_runs(telemetry)
        assert runs["greenhouse"]["added"] == 1 and runs["greenhouse"]["error"] is None
        assert runs["adzuna"]["added"] == 0 and "429" in runs["adzuna"]["error"]


def test_runner_note_includes_filtered_count(tmp_path):
    class _Conn:
        name = "fake"
        filtered = 7

        def fetch(self, search, limit=None):
            return []

    telemetry = tmp_path / "runs.json"
    with _session() as s:
        run_pull(s, [_Conn()], SearchConfig(), telemetry)
    note = read_runs(telemetry)["fake"]["error"] or ""
    assert "filtered 7" in note


class _UpgradingConnector:
    name = "companies"
    filtered = 0
    failures: dict[str, str] = {}

    def fetch(self, search, limit=None):
        return [RawJob("workday", "http://wd/1", "Acme", "Backend Engineer", "Remote", "full jd")]


def test_run_pull_records_upgrade_note(tmp_path):
    with _session() as s:
        save_job(
            s,
            Job(source="adzuna", jd_text="thin jd", url="http://adz/1",
                company="Acme", title="Backend Engineer", status=JobStatus.raw.value,
                dedup_key="acme|backend engineer"),
        )
        totals = run_pull(s, [_UpgradingConnector()], SearchConfig(), tmp_path / "runs.json")

    assert totals == {"companies": 0}
    runs = read_runs(tmp_path / "runs.json")
    assert runs["companies"]["added"] == 0
    assert "1 upgraded" in runs["companies"]["error"]


class _MixedConnector:
    """Fan-out connector whose sub-source labels never equal its own name."""

    name = "companies"
    filtered = 0
    failures: dict[str, str] = {}

    def fetch(self, search, limit=None):
        return [
            RawJob("google", "http://g/1", "Acme", "Frontend Engineer", "Remote", "google jd"),
            RawJob("workday", "http://wd/1", "Beta", "Backend Engineer", "Remote", "workday jd"),
        ]


def test_run_pull_attributes_mixed_added_and_upgraded_to_connector(tmp_path):
    # added/upgraded counters are keyed by sub-source ("google"/"workday"), never by the
    # connector name ("companies"), so the runner must fall back to summing sub-source values.
    with _session() as s:
        save_job(
            s,
            Job(source="adzuna", jd_text="thin jd", url="http://adz/1",
                company="Beta", title="Backend Engineer", status=JobStatus.raw.value,
                dedup_key="beta|backend engineer"),
        )
        totals = run_pull(s, [_MixedConnector()], SearchConfig(), tmp_path / "runs.json")

    assert totals == {"companies": 1}
    runs = read_runs(tmp_path / "runs.json")
    assert runs["companies"]["added"] == 1
    note = runs["companies"]["error"]
    assert "+1 added" in note and "1 upgraded" in note
