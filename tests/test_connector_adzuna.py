import json
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.adzuna import AdzunaConnector, parse_adzuna
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "adzuna" / "search.json").read_text())


def test_parse_adzuna_maps_nested_company_and_location():
    jobs = parse_adzuna(FIXTURE)
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "adzuna"
    assert first.company == "Acme Corp"
    assert first.location == "Remote, US"
    assert first.url == "https://www.adzuna.com/jobs/1"
    assert "Python" in first.jd_text


def test_parse_adzuna_sets_posted_at_from_created():
    payload = {
        "results": [
            {
                "title": "Eng",
                "redirect_url": "u",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Remote"},
                "description": "hi",
                "created": "2026-06-01T00:00:00Z",
            }
        ]
    }
    assert parse_adzuna(payload)[0].posted_at == datetime(
        2026, 6, 1, tzinfo=timezone.utc
    )


class _FakeAdzuna(AdzunaConnector):
    def _get_results(self, search):
        return FIXTURE


def test_connector_filters_by_search():
    connector = _FakeAdzuna(app_id="x", app_key="y", country="us")
    jobs = connector.fetch(SearchConfig(keywords=["kubernetes"]))
    assert {j.title for j in jobs} == {"Platform Engineer"}
    assert connector.name == "adzuna"
