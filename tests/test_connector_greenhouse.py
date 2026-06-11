import json
from pathlib import Path

from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector, parse_greenhouse
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "greenhouse" / "jobs.json").read_text())


def test_parse_greenhouse_maps_and_decodes_content():
    jobs = parse_greenhouse(FIXTURE, company="Stripe")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "greenhouse"
    assert first.company == "Stripe"
    assert first.title == "Senior Backend Engineer"
    assert first.location == "Remote - US"
    assert first.url == "https://boards.greenhouse.io/stripe/jobs/1"
    assert "payment" in first.jd_text and "<" not in first.jd_text


class _FakeGreenhouse(GreenhouseConnector):
    def _get_board(self, token):
        return FIXTURE


def test_connector_fetches_boards_and_filters_by_search():
    connector = _FakeGreenhouse([GreenhouseBoard(token="stripe", company="Stripe")])
    jobs = connector.fetch(SearchConfig(keywords=["python"]))
    assert {j.title for j in jobs} == {"Senior Backend Engineer"}
    assert connector.name == "greenhouse"
