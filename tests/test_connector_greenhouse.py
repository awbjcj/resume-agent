import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from resume_agent.discovery.url_ingest import fetch as url_fetch
from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.greenhouse import (
    GreenhouseConnector,
    parse_greenhouse,
)
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.discovery.url_ingest.models import PageContent

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "greenhouse" / "jobs.json").read_text()
)


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


def test_parse_greenhouse_sets_posted_at_from_updated_at():
    payload = {
        "jobs": [
            {
                "title": "Eng",
                "absolute_url": "u",
                "location": {"name": "Remote"},
                "content": "hi",
                "updated_at": "2026-06-01T00:00:00Z",
            }
        ]
    }
    jobs = parse_greenhouse(payload, "Acme")
    assert jobs[0].posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_parse_greenhouse_posted_at_none_when_absent():
    payload = {"jobs": [{"title": "Eng", "absolute_url": "u", "content": "hi"}]}
    assert parse_greenhouse(payload, "Acme")[0].posted_at is None


class _FakeGreenhouse(GreenhouseConnector):
    def _get_board(self, token):
        return FIXTURE


def test_connector_fetches_boards_and_filters_by_search():
    connector = _FakeGreenhouse([GreenhouseBoard(token="stripe", company="Stripe")])
    result = connector.fetch(SearchConfig(keywords=["python"]))
    assert {j.title for j in result.jobs} == {"Senior Backend Engineer"}
    assert connector.name == "greenhouse"


def test_greenhouse_gate_drops_offtarget_and_records_count(monkeypatch):
    conn = GreenhouseConnector([GreenhouseBoard(token="acme", company="Acme")])
    payload = {
        "jobs": [
            {
                "title": "AI Engineer",
                "absolute_url": "u1",
                "content": "build llm systems",
            },
            {
                "title": "Class A CDL Driver",
                "absolute_url": "u2",
                "content": "drive a truck",
            },
        ]
    }
    monkeypatch.setattr(conn, "_get_board", lambda token: payload)
    cfg = SearchConfig(role_anchors=["engineer", "ai"], exclude_terms=["driver", "cdl"])
    result = conn.fetch(cfg)
    assert [j.title for j in result.jobs] == ["AI Engineer"]
    assert result.filtered == 1


class _PartlyBrokenGreenhouse(GreenhouseConnector):
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
    connector = _PartlyBrokenGreenhouse(
        [
            GreenhouseBoard(token="dead", company="Dead Co"),
            GreenhouseBoard(token="stripe", company="Stripe"),
        ]
    )
    result = connector.fetch(SearchConfig(keywords=["python"]))
    # A 404 on the first board must NOT abort the remaining boards.
    assert {j.company for j in result.jobs} == {"Stripe"}
    assert "dead" in result.failures
    assert "404" in result.failures["dead"]


def test_get_board_delegates_to_module_fetcher(monkeypatch):
    import resume_agent.discovery.connectors.greenhouse as gh

    called = {}

    def fake_fetch(token):
        called["token"] = token
        return {"jobs": []}

    monkeypatch.setattr(gh, "fetch_greenhouse_board", fake_fetch)
    conn = gh.GreenhouseConnector([GreenhouseBoard(token="acme")])
    assert conn._get_board("acme") == {"jobs": []}
    assert called["token"] == "acme"


def test_greenhouse_per_board_limit_overrides_global(monkeypatch):
    boards = [
        GreenhouseBoard(token="alpha", limit=1),
        GreenhouseBoard(token="beta"),
    ]
    connector = GreenhouseConnector(boards)
    payload = {
        "jobs": [
            {
                "title": f"Engineer {index}",
                "absolute_url": f"http://x/{index}",
                "location": {"name": "Remote"},
                "content": "Python",
            }
            for index in range(3)
        ]
    }
    monkeypatch.setattr(connector, "_get_board", lambda token: payload)
    monkeypatch.setattr(connector, "_get_board_name", lambda token: None)
    result = connector.fetch(SearchConfig(role_anchors=["Engineer"]), limit=2)
    assert len(result.jobs) == 3
    assert [job.company for job in result.jobs] == ["alpha", "beta", "beta"]


def test_parse_greenhouse_prepends_sidebar_facts():
    """Location/workplace/department ride in jd_text as `Label: value` lines.

    The board API returns these as dedicated fields the posting page renders
    beside the body; dropping them lost the facts the fit scorer reads.
    """
    payload = {
        "jobs": [
            {
                "title": "Eng",
                "absolute_url": "u",
                "content": "<p>Build things.</p>",
                "location": {"name": "Toronto, ON"},
                "departments": [{"name": "Payments Eng"}],
                "metadata": [
                    {
                        "name": "Location Type",
                        "value": "Hybrid",
                        "value_type": "single_select",
                    }
                ],
            }
        ]
    }
    jd = parse_greenhouse(payload, "Acme")[0].jd_text
    assert jd.startswith("Location: Toronto, ON")
    assert "Workplace Type: Hybrid" in jd
    assert "Department: Payments Eng" in jd
    assert "Build things." in jd


def test_parse_greenhouse_omits_placeholder_location_and_null_metadata():
    """Greenhouse serves the literal string "N/A" for an unset location, and a
    metadata entry whose value is null. Neither may become a meta line."""
    payload = {
        "jobs": [
            {
                "title": "Eng",
                "absolute_url": "u",
                "content": "<p>Build things.</p>",
                "location": {"name": "N/A"},
                "metadata": [
                    {
                        "name": "Location Type",
                        "value": None,
                        "value_type": "single_select",
                    }
                ],
            }
        ]
    }
    jd = parse_greenhouse(payload, "Acme")[0].jd_text
    assert "Location:" not in jd
    assert "Workplace Type:" not in jd
    assert jd.startswith("Build things.")


def test_parse_greenhouse_deduplicates_composite_location():
    payload = {
        "jobs": [
            {
                "title": "Software Engineer, Research Tools",
                "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/4981828008",
                "content": "<p>Build research tools.</p>",
                "location": {
                    "name": (
                        "San Francisco, CA | New York City, NY; "
                        "San Francisco, CA | New York City, NY | Seattle, WA"
                    )
                },
            }
        ]
    }

    job = parse_greenhouse(payload, "Anthropic")[0]

    expected = "San Francisco, CA | New York City, NY | Seattle, WA"
    assert job.location == expected
    assert job.jd_text.startswith(f"Location: {expected}")


def test_connector_enriches_employer_hosted_greenhouse_posting(monkeypatch):
    payload = {
        "jobs": [
            {
                "title": "Backend Engineer, Developer SDKs (Golang)",
                "absolute_url": "https://stripe.com/jobs/search?gh_jid=7557899",
                "location": {"name": "N/A"},
                "content": "<h2>Who we are</h2><p>Build SDKs.</p>",
            }
        ]
    }
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type":"JobPosting","title":"Backend Engineer, Developer SDKs (Golang)",
         "description":"<p>Build SDKs.</p>","hiringOrganization":{"name":"Stripe"},
         "employmentType":"FULL_TIME","jobLocation":{"address":{"addressLocality":"Toronto",
         "addressCountry":"CA"}},"baseSalary":{"currency":"CAD","value":{"minValue":135200,
         "maxValue":258000,"unitText":"YEAR"}}}
      </script>
      <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"listing":{"greenhouseId":7557899,
         "title":"Backend Engineer, Developer SDKs (Golang)",
         "contentMarkdown":"## Who we are\\n\\nBuild SDKs.",
         "location":{"name":"Toronto","countryCode":"CA","remote":false},
         "employmentType":"Full time"}}}}
      </script>
    </head><body><main><div class="careers-detail-layout__main">
      <div class="careers-listing-details__body"><h2>Who we are</h2><p>Build SDKs.</p></div>
      <div class="careers-listing-details__body"><h2>In-office expectations</h2>
        <p>Spend at least 50% of each month in the office.</p></div>
      <div class="careers-listing-details__body"><h2>Pay and benefits</h2>
        <p>CA$135,200 - CA$258,000 plus health benefits.</p></div>
    </div></main></body></html>
    """
    connector = GreenhouseConnector([GreenhouseBoard(token="stripe", company="Stripe")])
    monkeypatch.setattr(connector, "_get_board", lambda token: payload)
    monkeypatch.setattr(
        url_fetch,
        "fetch_static",
        lambda url: PageContent(
            html=html,
            final_url=(
                "https://stripe.com/careers/listing/"
                "backend-engineer-developer-sdks-golang/7557899?gh_jid=7557899"
            ),
            rendered=False,
        ),
    )

    result = connector.fetch(SearchConfig(role_anchors=["Engineer"]), limit=1)

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.location == "Toronto, CA"
    assert "In-office expectations" in job.jd_text
    assert "Pay and benefits" in job.jd_text
    assert "Compensation: CAD 135,200 - 258,000 per year" in job.jd_text
