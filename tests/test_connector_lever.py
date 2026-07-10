import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from resume_agent.discovery.connectors.config import LeverBoard
from resume_agent.discovery.connectors.lever import (
    LeverConnector,
    fetch_lever_board,
    parse_lever,
)
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "lever" / "postings.json").read_text()
)


def test_parse_lever_maps_and_assembles_full_jd():
    jobs = parse_lever(FIXTURE, company="Acme")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "lever"
    assert first.company == "Acme"
    assert first.title == "Senior Backend Engineer"
    assert first.location == "Remote - US"
    assert first.url == "https://jobs.lever.co/acme/abc-123"
    # Opening, the Requirements list, and the closing are all present, tag-free.
    assert "payment" in first.jd_text
    assert "Requirements" in first.jd_text
    assert "5+ years of Python." in first.jd_text
    assert "great benefits" in first.jd_text
    assert "<" not in first.jd_text


def test_parse_lever_sets_posted_at_from_created_at_millis():
    jobs = parse_lever(FIXTURE, company="Acme")
    assert jobs[0].posted_at == datetime(2025, 6, 1, tzinfo=timezone.utc)


def test_parse_lever_posted_at_none_when_absent():
    payload = [{"text": "Eng", "hostedUrl": "u", "description": "hi"}]
    assert parse_lever(payload, "Acme")[0].posted_at is None


class _FakeLever(LeverConnector):
    def _get_board(self, token, search):
        return FIXTURE


def test_connector_fetches_boards_and_filters_by_search():
    connector = _FakeLever([LeverBoard(token="acme", company="Acme")])
    result = connector.fetch(SearchConfig(keywords=["python"]))
    assert {j.title for j in result.jobs} == {"Senior Backend Engineer"}
    assert connector.name == "lever"


class _PartlyBrokenLever(LeverConnector):
    """First board 404s; the rest return the fixture payload."""

    def _get_board(self, token, search):
        if token == "dead":
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(404),
            )
        return FIXTURE


def test_connector_isolates_failing_board_and_records_it():
    connector = _PartlyBrokenLever(
        [
            LeverBoard(token="dead", company="Dead Co"),
            LeverBoard(token="acme", company="Acme"),
        ]
    )
    result = connector.fetch(SearchConfig(keywords=["python"]))
    # A 404 on the first board must NOT abort the remaining boards.
    assert {j.company for j in result.jobs} == {"Acme"}
    assert "dead" in result.failures
    assert "404" in result.failures["dead"]


def test_get_board_delegates_to_module_fetcher(monkeypatch):
    import resume_agent.discovery.connectors.lever as lever

    called = {}

    def fake_fetch(token, search=None):
        called["token"] = token
        return []

    monkeypatch.setattr(lever, "fetch_lever_board", fake_fetch)
    conn = lever.LeverConnector([LeverBoard(token="acme")])
    assert conn._get_board("acme", SearchConfig()) == []
    assert called["token"] == "acme"


def test_fetch_lever_board_pushes_location(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return Response()

    import resume_agent.discovery.connectors.lever as lever

    monkeypatch.setattr(lever.httpx, "get", fake_get)
    fetch_lever_board("acme", SearchConfig(locations=["Remote"]))

    assert captured["params"] == {"mode": "json", "location": "Remote"}


def test_lever_per_board_limit_overrides_global(monkeypatch):
    boards = [LeverBoard(token="alpha", limit=1), LeverBoard(token="beta")]
    connector = LeverConnector(boards)
    payload = [
        {
            "text": f"Engineer {index}",
            "hostedUrl": f"http://x/{index}",
            "description": "Python",
        }
        for index in range(3)
    ]
    monkeypatch.setattr(connector, "_get_board", lambda token, search: payload)
    result = connector.fetch(SearchConfig(role_anchors=["Engineer"]), limit=2)
    assert len(result.jobs) == 3
    assert [job.company for job in result.jobs] == ["alpha", "beta", "beta"]
