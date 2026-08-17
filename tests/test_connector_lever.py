import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from resume_agent.discovery.connectors.config import LeverBoard
from resume_agent.discovery.connectors.lever import (
    LeverConnector,
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
    def _get_board(self, token):
        return FIXTURE


def test_connector_fetches_boards_and_filters_by_search():
    connector = _FakeLever([LeverBoard(token="acme", company="Acme")])
    result = connector.fetch(SearchConfig(keywords=["python"]))
    assert {j.title for j in result.jobs} == {"Senior Backend Engineer"}
    assert connector.name == "lever"


class _PartlyBrokenLever(LeverConnector):
    """First board 404s; the rest return the fixture payload."""

    def _get_board(self, token):
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

    def fake_fetch(token):
        called["token"] = token
        return []

    monkeypatch.setattr(lever, "fetch_lever_board", fake_fetch)
    conn = lever.LeverConnector([LeverBoard(token="acme")])
    assert conn._get_board("acme") == []
    assert called["token"] == "acme"


def test_lever_never_pushes_location_even_when_configured(monkeypatch):
    # Lever's ?location= filter is an exact, case-sensitive string match, so any
    # near-miss (e.g. "Remote" vs a posting's "Remote - US") silently zeroes the
    # whole board. Like Greenhouse/Ashby, Lever must fetch every posting and let
    # the local relevance gate decide — never pre-filter server-side by location,
    # even when the search config carries one.
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return Response()

    import resume_agent.discovery.connectors.lever as lever

    monkeypatch.setattr(lever.board, "get", fake_get)
    LeverConnector([LeverBoard(token="acme")]).fetch(
        SearchConfig(locations=["Remote"])
    )

    assert captured["params"] == {"mode": "json"}


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
    monkeypatch.setattr(connector, "_get_board", lambda token: payload)
    result = connector.fetch(SearchConfig(role_anchors=["Engineer"]), limit=2)
    assert len(result.jobs) == 3
    assert [job.company for job in result.jobs] == ["alpha", "beta", "beta"]


def test_parse_lever_prepends_sidebar_facts():
    """Lever's sidebar facts live in dedicated fields, not in the JD body.

    Field names and shapes verified live against the zoox and matchgroup
    boards (328 postings).
    """
    payload = [
        {
            "text": "Eng",
            "hostedUrl": "u",
            "description": "<p>Build things.</p>",
            "workplaceType": "hybrid",
            "categories": {
                "location": "Foster City, CA",
                "allLocations": ["Foster City, CA", "San Diego, CA"],
                "commitment": "Full-time",
                "department": "Software",
                "team": "Software Quality Assurance",
                "level": "Senior",
            },
            "salaryRange": {
                "min": 143000,
                "max": 177000,
                "currency": "USD",
                "interval": "per-year-salary",
            },
        }
    ]
    job = parse_lever(payload, "Zoox")[0]
    jd = job.jd_text
    assert job.location == "Foster City, CA | San Diego, CA"
    assert jd.startswith("Location: Foster City, CA (also: San Diego, CA)")
    assert "Workplace Type: Hybrid" in jd
    assert "Employment Type: Full-time" in jd
    assert "Department: Software (Software Quality Assurance)" in jd
    assert "Level: Senior" in jd
    assert "Compensation: USD 143,000 - 177,000 per year" in jd
    assert "Build things." in jd


def test_parse_lever_sidebar_omits_absent_fields_and_redundant_team():
    """A posting with no salary/level/commitment renders none of those lines,
    and a team identical to the department is not repeated in parentheses."""
    payload = [
        {
            "text": "Eng",
            "hostedUrl": "u",
            "description": "<p>Build things.</p>",
            "categories": {"location": "Remote", "department": "Eng", "team": "Eng"},
        }
    ]
    jd = parse_lever(payload, "Acme")[0].jd_text
    assert jd.startswith("Location: Remote\nDepartment: Eng\n\n")
    assert "Compensation:" not in jd
    assert "Level:" not in jd
    assert "Employment Type:" not in jd
    assert "Workplace Type:" not in jd


def test_parse_lever_includes_salary_description_prose():
    """`salaryDescription` is a separate pay-and-benefits section Lever renders
    below the body -- present on 212 of zoox's 244 postings and previously
    dropped entirely, since _assemble_jd read only description/lists/additional.
    """
    payload = [
        {
            "text": "Eng",
            "hostedUrl": "u",
            "description": "<p>Build things.</p>",
            "salaryDescription": "<p>Base Salary Range: RSUs and a sign-on bonus may apply.</p>",
            "additional": "<p>Equal opportunity employer.</p>",
        }
    ]
    jd = parse_lever(payload, "Acme")[0].jd_text
    assert "Base Salary Range" in jd
    assert "sign-on bonus" in jd
    # ordering: body, then pay prose, then the closing boilerplate
    assert jd.index("Build things.") < jd.index("Base Salary Range")
    assert jd.index("Base Salary Range") < jd.index("Equal opportunity employer.")
