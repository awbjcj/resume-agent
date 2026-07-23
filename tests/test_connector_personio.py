from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.personio import (
    fetch_personio,
    parse_personio,
    search_url,
)
from resume_agent.discovery.search_config import SearchConfig


def _fixture() -> str:
    return (Path(__file__).parent / "fixtures" / "personio" / "search.json").read_text()


def test_personio_maps_search_json_and_converts_html():
    jobs = parse_personio(_fixture(), "pitch", "de")

    assert search_url("pitch", "de") == "https://pitch.jobs.personio.de/search.json?language=en"
    assert jobs[0].company == "Pitch Software GmbH"
    assert jobs[0].title == "Frontend Performance Engineer"
    assert jobs[0].location == "Berlin // Remote"
    assert jobs[0].url == "https://pitch.jobs.personio.de/job/160959"
    assert "- Five years building frontend systems" in jobs[0].jd_text


def test_personio_keeps_postings_without_description():
    jobs = parse_personio(_fixture(), "pitch", "de")

    # Evergreen "Initiativbewerbung" rows have an empty description but still surface.
    assert jobs[1].title == "Initiativbewerbung"
    assert jobs[1].jd_text == ""


def test_personio_fetch_uses_search_json_with_detected_country(monkeypatch):
    captured = {}

    class Response:
        text = _fixture()

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None, follow_redirects=None):
        captured["url"] = url
        return Response()

    import resume_agent.discovery.connectors.personio as connector

    monkeypatch.setattr(connector.httpx, "get", fake_get)
    jobs = fetch_personio(AtsTarget("personio", "pitch", country="de"), SearchConfig())

    assert captured["url"] == "https://pitch.jobs.personio.de/search.json?language=en"
    assert jobs[0].jd_text
