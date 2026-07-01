import json
from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.recruitee import (
    fetch_recruitee,
    offers_url,
    parse_recruitee,
)
from resume_agent.discovery.search_config import SearchConfig


def test_recruitee_maps_public_offers_payload():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "recruitee" / "offers.json").read_text()
    )
    jobs = parse_recruitee(payload, "transperfect")

    assert (
        offers_url("transperfect") == "https://transperfect.recruitee.com/api/offers/"
    )
    assert jobs[0].company == "TransPerfect"
    assert jobs[0].url.endswith("/c/new")
    assert "SQL expertise" in jobs[0].jd_text


def test_recruitee_fetch_reads_public_offers(monkeypatch):
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "recruitee" / "offers.json").read_text()
    )

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    import resume_agent.discovery.connectors.recruitee as connector

    monkeypatch.setattr(connector.httpx, "get", lambda *args, **kwargs: Response())
    assert fetch_recruitee(AtsTarget("recruitee", "transperfect"), SearchConfig())[
        0
    ].jd_text
