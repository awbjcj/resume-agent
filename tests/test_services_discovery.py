from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services import discovery


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_add_job_from_text_inserts(tmp_path):
    with _session() as session:
        job = discovery.add_job_from_text(
            session, jd_text="We need a Python engineer.", company="Acme", title="SWE"
        )
    assert job is not None
    assert job.source == "manual"
    assert job.company == "Acme"


def test_discover_jobs_delegates_to_pipeline(monkeypatch, tmp_path):
    captured = {}

    def fake_discover(session, config, facts, extract, fit, relevance, canonicalizer=None, reporter=None):
        captured["called"] = True
        return {"raw": 0, "shortlisted": 2}

    monkeypatch.setattr(discovery, "discover", fake_discover)
    monkeypatch.setattr(discovery, "load_search_config", lambda p: object())
    monkeypatch.setattr(discovery, "load_facts", lambda p: object())
    monkeypatch.setattr(
        discovery, "build_discovery_bundle",
        lambda: discovery.DiscoveryBundle(extract="e", fit="f", relevance="r", canonicalizer="c"),
    )
    with _session() as session:
        counts = discovery.discover_jobs(session, search_path="x", facts_path="y")
    assert counts == {"raw": 0, "shortlisted": 2}
    assert captured["called"]
