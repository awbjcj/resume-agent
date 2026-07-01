import json
from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.smartrecruiters import (
    apply_detail,
    fetch_smartrecruiters,
    list_params,
    parse_postings,
)
from resume_agent.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "smartrecruiters"


def test_smartrecruiters_maps_list_and_detail():
    rows = parse_postings(
        json.loads((FIXTURES / "list.json").read_text()), "smartrecruiters"
    )
    apply_detail(rows[0], json.loads((FIXTURES / "detail.json").read_text()))

    assert rows[0].company == "SmartRecruiters Inc"
    assert rows[0].location == "United States, REMOTE, us"
    assert rows[0].url is not None
    assert rows[0].url.startswith("https://jobs.smartrecruiters.com/")
    assert "Enterprise SaaS experience" in rows[0].jd_text


def test_smartrecruiters_pushes_only_supported_search_text():
    params = list_params(
        SearchConfig(titles=[" Software Engineer "], locations=["Austin, TX"]), 0
    )

    assert params == {"limit": 100, "offset": 0, "q": "Software Engineer"}


def test_smartrecruiters_fetch_wires_list_to_detail(monkeypatch):
    list_payload = json.loads((FIXTURES / "list.json").read_text())
    detail_payload = json.loads((FIXTURES / "detail.json").read_text())
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return Response(list_payload if params is not None else detail_payload)

    import resume_agent.discovery.connectors.smartrecruiters as connector

    monkeypatch.setattr(connector.httpx, "get", fake_get)
    jobs = fetch_smartrecruiters(
        AtsTarget("smartrecruiters", "smartrecruiters"),
        SearchConfig(role_anchors=["product"]),
    )

    assert len(calls) == 2
    assert jobs[0].jd_text


def test_smartrecruiters_known_url_skips_detail_request(monkeypatch):
    list_payload = json.loads((FIXTURES / "list.json").read_text())
    posting_id = list_payload["content"][0]["id"]
    known_url = f"https://jobs.smartrecruiters.com/smartrecruiters/{posting_id}"
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return list_payload

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return Response()

    import resume_agent.discovery.connectors.smartrecruiters as connector

    monkeypatch.setattr(connector.httpx, "get", fake_get)
    jobs = fetch_smartrecruiters(
        AtsTarget("smartrecruiters", "smartrecruiters"),
        SearchConfig(),
        skip_seen=lambda row: row.url == known_url,
    )

    assert jobs == []
    assert calls == [
        "https://api.smartrecruiters.com/v1/companies/smartrecruiters/postings"
    ]
