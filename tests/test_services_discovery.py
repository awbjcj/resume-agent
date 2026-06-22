import httpx
import pytest

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.services import discovery
from resume_agent.services.discovery import UrlFetchError


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


def test_discover_jobs_delegates_and_forwards_bundle(monkeypatch, tmp_path):
    seen = {}

    def fake_discover(session, config, facts, extract, fit, relevance, canonicalizer=None, reporter=None):
        seen["relevance"] = relevance
        seen["canonicalizer"] = canonicalizer
        return {"raw": 0, "shortlisted": 2}

    monkeypatch.setattr(discovery, "discover", fake_discover)
    monkeypatch.setattr(discovery, "load_search_config", lambda p: object())
    monkeypatch.setattr(discovery, "load_facts", lambda p: object())
    monkeypatch.setattr(
        discovery, "build_discovery_bundle",
        lambda: discovery.DiscoveryBundle(extract="e", fit="f", relevance="r", canonicalizer="c"),  # type: ignore[arg-type]
    )
    with _session() as session:
        counts = discovery.discover_jobs(session, search_path="x", facts_path="y")
    assert counts == {"raw": 0, "shortlisted": 2}
    assert seen == {"relevance": "r", "canonicalizer": "c"}


def test_add_job_from_url_extracts_and_overrides(monkeypatch):
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(
        discovery, "job_from_url",
        lambda url, *, agent, allow_browser=True: RawJob(
            source="url", url=url, company="Acme", title="Engineer",
            location="Remote", jd_text="Build.",
        ),
    )
    with _session() as session:
        job = discovery.add_job_from_url(session, url="https://x/job", company="Globex")
    assert job is not None
    assert job.company == "Globex"  # explicit override wins
    assert job.title == "Engineer"  # extracted value kept


def test_add_job_from_url_raises_on_fetch_error(monkeypatch):
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())

    def _raise(url, *, agent, allow_browser=True):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(discovery, "job_from_url", _raise)
    with _session() as session:
        with pytest.raises(UrlFetchError, match="Couldn't fetch"):
            discovery.add_job_from_url(session, url="https://x/job")


def test_add_job_from_url_raises_when_no_extraction(monkeypatch):
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(discovery, "job_from_url", lambda url, *, agent, allow_browser=True: None)
    with _session() as session:
        with pytest.raises(UrlFetchError, match="Couldn't extract"):
            discovery.add_job_from_url(session, url="https://x/job")
