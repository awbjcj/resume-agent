import json
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.remoteok import RemoteOKConnector, parse_remoteok
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "remoteok" / "api.json").read_text())


def test_parse_remoteok_skips_legal_header_and_maps_jobs():
    jobs = parse_remoteok(FIXTURE)
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "remoteok"
    assert first.title == "Backend Engineer"
    assert first.company == "Acme"
    assert first.location == "Worldwide"
    assert "Python" in first.jd_text and "<" not in first.jd_text


def test_parse_remoteok_defaults_blank_location_to_remote():
    jobs = parse_remoteok(FIXTURE)
    assert jobs[1].location == "Remote"


def test_parse_remoteok_sets_posted_at_from_date():
    payload = [
        {
            "position": "Eng",
            "company": "Acme",
            "url": "u",
            "description": "hi",
            "date": "2026-06-01T00:00:00+00:00",
        }
    ]
    assert parse_remoteok(payload)[0].posted_at == datetime(
        2026, 6, 1, tzinfo=timezone.utc
    )


class _FakeRemoteOK(RemoteOKConnector):
    def _get_all(self):
        return FIXTURE


def test_connector_filters_by_search():
    connector = _FakeRemoteOK()
    result = connector.fetch(SearchConfig(keywords=["react"]))
    assert {j.title for j in result.jobs} == {"Frontend Engineer"}
    assert connector.name == "remoteok"
