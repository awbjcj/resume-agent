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
    with _session() as session:
        discovery.pull_jobs(session, source_ids=["greenhouse:anthropic"])

    assert captured["source_ids"] == ["greenhouse:anthropic"]
