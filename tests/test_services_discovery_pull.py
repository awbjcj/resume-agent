from sqlmodel import Session, SQLModel, create_engine

from resume_agent.services import discovery


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
    monkeypatch.setattr(discovery, "load_search_config", lambda path: object())
    monkeypatch.setattr(discovery, "load_connectors_config", lambda path: object())
    with _session() as session:
        discovery.pull_jobs(session, source_ids=["greenhouse:anthropic"])

    assert captured["source_ids"] == ["greenhouse:anthropic"]


def test_pull_jobs_forwards_skip_known(monkeypatch):
    captured = {}

    def fake_run_pull(session, connectors, search, telemetry_path, **kwargs):
        captured.update(kwargs)
        from resume_agent.discovery.connectors.runner import PullReport

        return PullReport()

    monkeypatch.setattr(discovery, "run_pull", fake_run_pull)
    monkeypatch.setattr(
        discovery, "build_source_connectors", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(discovery, "load_search_config", lambda path: object())
    monkeypatch.setattr(discovery, "load_connectors_config", lambda path: object())
    with _session() as session:
        discovery.pull_jobs(session, skip_known=False)

    assert captured["skip_known"] is False
