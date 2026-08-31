import threading

from sqlmodel import Session

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.discovery.connectors.base import FetchResult, RawJob
from resume_tailor_harness.discovery.connectors.runner import run_pull
from resume_tailor_harness.discovery.search_config import SearchConfig


class _HandshakeConnector:
    """fetch() blocks until its peer has also started -> only passes if the two
    fetches run concurrently."""

    concurrent_fetch = True

    def __init__(self, name: str, mine: threading.Event, peer: threading.Event):
        self.name = name
        self._mine = mine
        self._peer = peer

    def fetch(self, search, limit=None, skip_seen=None) -> FetchResult:
        self._mine.set()
        assert self._peer.wait(timeout=10), "peer fetch never started concurrently"
        return FetchResult(
            jobs=[
                RawJob(
                    source=self.name,
                    url=None,
                    company="Acme",
                    title=f"{self.name} role",
                    location=None,
                    jd_text=f"jd from {self.name}",
                )
            ]
        )


class _FailingConnector:
    concurrent_fetch = True
    name = "broken"

    def fetch(self, search, limit=None, skip_seen=None) -> FetchResult:
        raise RuntimeError("boom")


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'pull.db'}")
    init_db(engine)
    return Session(engine)


def test_fetches_overlap_and_ingest_is_ordered(tmp_path):
    a_started, b_started = threading.Event(), threading.Event()
    connectors = [
        _HandshakeConnector("alpha", a_started, b_started),
        _HandshakeConnector("beta", b_started, a_started),
    ]
    with _session(tmp_path) as session:
        report = run_pull(
            session, connectors, SearchConfig(), tmp_path / "telemetry.json"
        )
    assert report.totals == {"alpha": 1, "beta": 1}


def test_failed_fetch_is_isolated(tmp_path):
    a_started, b_started = threading.Event(), threading.Event()
    b_started.set()  # no peer to wait for
    connectors = [
        _FailingConnector(),
        _HandshakeConnector("alpha", a_started, b_started),
    ]
    with _session(tmp_path) as session:
        report = run_pull(
            session, connectors, SearchConfig(), tmp_path / "telemetry.json"
        )
    assert report.totals == {"alpha": 1}
    assert "broken" not in report.totals
