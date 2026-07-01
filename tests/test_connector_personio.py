from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.personio import (
    feed_url,
    fetch_personio,
    parse_personio,
)
from resume_agent.discovery.search_config import SearchConfig


def test_personio_maps_xml_feed_and_preserves_lists():
    xml = (Path(__file__).parent / "fixtures" / "personio" / "feed.xml").read_text()
    jobs = parse_personio(xml, "pitch", "de")

    assert feed_url("pitch", "de") == "https://pitch.jobs.personio.de/xml"
    assert jobs[0].company == "Pitch Software GmbH"
    assert jobs[0].url == "https://pitch.jobs.personio.de/job/160959"
    assert "- Five years" in jobs[0].jd_text


def test_personio_fetch_uses_detected_country_suffix(monkeypatch):
    xml = (Path(__file__).parent / "fixtures" / "personio" / "feed.xml").read_text()
    captured = {}

    class Response:
        text = xml

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None):
        captured["url"] = url
        return Response()

    import resume_agent.discovery.connectors.personio as connector

    monkeypatch.setattr(connector.httpx, "get", fake_get)
    jobs = fetch_personio(AtsTarget("personio", "pitch", country="de"), SearchConfig())

    assert captured["url"].endswith("personio.de/xml")
    assert jobs[0].jd_text
