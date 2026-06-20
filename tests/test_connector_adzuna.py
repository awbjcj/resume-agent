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
    result = connector.fetch(SearchConfig(keywords=["kubernetes"]))
    assert {j.title for j in result.jobs} == {"Platform Engineer"}
    assert connector.name == "adzuna"


def test_adzuna_builds_targeted_params():
    conn = AdzunaConnector("id", "key", country="us")
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"results": []}

        return _R()

    import resume_agent.discovery.connectors.adzuna as mod

    orig = mod.httpx.get
    mod.httpx.get = fake_get
    try:
        cfg = SearchConfig(
            role_anchors=["ai engineer", "machine learning"],
            keywords=["llm", "rag"],
            exclude_terms=["driver", "cdl"],
            locations=["Detroit, MI"],
            min_salary=130000,
            distance=40,
            max_days_old=30,
        )
        conn.fetch(cfg)
    finally:
        mod.httpx.get = orig

    p = captured["params"]
    assert captured["url"].endswith("/us/search/1")
    assert "ai engineer" in p["what_or"] and "machine learning" in p["what_or"]
    assert "driver" in p["what_exclude"] and "cdl" in p["what_exclude"]
    assert p["category"] == "it-jobs"
    assert p["results_per_page"] == 50
    assert p["where"] == "Detroit, MI" and p["distance"] == 40
    assert p["salary_min"] == 130000
    assert p["max_days_old"] == 30
    assert "what" not in p
