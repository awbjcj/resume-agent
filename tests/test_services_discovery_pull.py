from sqlmodel import Session, SQLModel, create_engine

from resume_agent.services import discovery
from resume_agent.discovery.connectors.runner import PullReport
from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.search_config import SearchConfig


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_pull_jobs_passes_source_ids_to_per_entry_build(monkeypatch):
    captured = {}

    def fake_build(config, settings, source_ids=None):
        captured["source_ids"] = source_ids
        return []

    monkeypatch.setattr(discovery, "build_source_connectors", fake_build)
    with _session() as session:
        discovery.pull_jobs(session, source_ids=["greenhouse:anthropic"])

    assert captured["source_ids"] == ["greenhouse:anthropic"]


def test_pull_jobs_sets_relearn_on_dashboard_scrapers(monkeypatch):
    scraper = DashboardScraper([])
    observed = {}

    monkeypatch.setattr(discovery, "load_search_config", lambda path: SearchConfig())
    monkeypatch.setattr(discovery, "load_connectors_config", lambda path: object())
    monkeypatch.setattr(discovery, "build_source_connectors", lambda *args, **kwargs: [scraper])

    def fake_run_pull(session, connectors, search, telemetry_path, **kwargs):
        observed["relearn"] = connectors[0].relearn
        return PullReport()

    monkeypatch.setattr(discovery, "run_pull", fake_run_pull)

    discovery.pull_jobs(session=None, relearn=True)

    assert observed["relearn"] is True
