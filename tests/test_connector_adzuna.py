import json
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.adzuna import (
    AdzunaConnector,
    enrich_adzuna_job,
    enrich_adzuna_jobs,
    parse_adzuna,
)
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.discovery.url_ingest.models import PageContent

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "adzuna" / "search.json").read_text()
)


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
    def __init__(self):
        super().__init__(app_id="x", app_key="y", country="us", enrich_details=False)

    def _get_results(self, search):
        return FIXTURE


def test_connector_filters_by_search():
    connector = _FakeAdzuna()
    result = connector.fetch(SearchConfig(keywords=["kubernetes"]))
    assert {j.title for j in result.jobs} == {"Platform Engineer"}
    assert connector.name == "adzuna"


def test_adzuna_configured_limit_overrides_global(monkeypatch):
    connector = AdzunaConnector(
        "id", "key", enrich_details=False, configured_limit=1
    )
    payload = {
        "results": [
            {
                "redirect_url": f"https://a/{index}",
                "title": f"Engineer {index}",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Remote"},
                "description": "Python",
            }
            for index in range(3)
        ]
    }
    monkeypatch.setattr(connector, "_get_results", lambda search: payload)
    result = connector.fetch(SearchConfig(role_anchors=["Engineer"]), limit=5)
    assert len(result.jobs) == 1


def test_connector_skips_known_before_enrichment_and_then_applies_limit(monkeypatch):
    payload = {
        "results": [
            {
                "redirect_url": f"https://a/{index}",
                "title": "Backend Engineer",
                "company": {"display_name": f"Company {index}"},
                "location": {"display_name": "Remote"},
                "description": "Python backend services",
            }
            for index in range(3)
        ]
    }
    connector = AdzunaConnector("id", "key")
    monkeypatch.setattr(connector, "_get_results", lambda search: payload)
    rendered = []

    def fake_enrich(jobs):
        rendered.extend(job.url for job in jobs)
        return jobs, {}

    import resume_agent.discovery.connectors.adzuna as mod

    monkeypatch.setattr(mod, "enrich_adzuna_jobs", fake_enrich)
    result = connector.fetch(
        SearchConfig(role_anchors=["engineer"]),
        limit=2,
        skip_seen=lambda row: row.url == "https://a/0",
    )

    assert rendered == ["https://a/1", "https://a/2"]
    assert [job.url for job in result.jobs] == rendered


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


def _raw(jd_text="Short Python preview.", url="https://www.adzuna.com/jobs/1"):
    return RawJob(
        source="adzuna",
        url=url,
        company="Acme",
        title="Platform Engineer",
        location="Remote",
        jd_text=jd_text,
    )


def test_enrich_adzuna_job_replaces_snippet_from_jobposting_json_ld():
    words = " ".join(f"detail{i}" for i in range(70))
    html = f"""
    <html><head>
      <script type="application/ld+json">
      {{"@type":"JobPosting","description":"<p>Build Python services.</p><p>{words}</p>"}}
      </script>
    </head><body>shell</body></html>
    """
    page = PageContent(
        html=html, final_url="https://company.example/jobs/1", rendered=True
    )

    enriched = enrich_adzuna_job(_raw(), page)

    assert enriched.url == "https://www.adzuna.com/jobs/1"
    assert enriched.company == "Acme"
    assert "Build Python services." in enriched.jd_text
    assert "detail69" in enriched.jd_text


def test_enrich_adzuna_job_keeps_markdown_structure_from_dom():
    items = "".join(f"<li>requirement {i} bullet item</li>" for i in range(20))
    html = f"""
    <html><body>
      <div class="job-description">
        <h2>Responsibilities</h2>
        <ul>{items}</ul>
      </div>
    </body></html>
    """
    page = PageContent(
        html=html, final_url="https://company.example/jobs/1", rendered=True
    )

    enriched = enrich_adzuna_job(_raw(), page)

    # Markdown (not flat text): heading + bullets survive for display/extraction.
    assert "## Responsibilities" in enriched.jd_text
    assert "- requirement 0 bullet item" in enriched.jd_text


def test_enrich_adzuna_job_strips_logo_images():
    body = " ".join(f"para {i} text content here" for i in range(20))
    html = f"""
    <html><body>
      <div class="job-description">
        <img src="https://cdn.example/logo.png" alt="Acme logo"/>
        <p>{body}</p>
      </div>
    </body></html>
    """
    page = PageContent(
        html=html, final_url="https://company.example/jobs/1", rendered=True
    )

    enriched = enrich_adzuna_job(_raw(), page)

    assert "![" not in enriched.jd_text  # logo markdown removed
    assert "logo.png" not in enriched.jd_text
    assert enriched.jd_text.startswith("para 0 text content here")


def test_enrich_adzuna_job_keeps_snippet_when_page_missing():
    raw = _raw()
    assert enrich_adzuna_job(raw, None) is raw


def test_enrich_jobs_batch_renders_once_and_enriches(monkeypatch):
    words = " ".join(f"word{i}" for i in range(80))
    page = PageContent(
        html=f"<html><body><article>{words}</article></body></html>",
        final_url="https://company.example/jobs/1",
        rendered=True,
    )
    calls = {}

    def fake_render_pages(urls):
        calls["urls"] = list(urls)
        return {"https://www.adzuna.com/jobs/1": page}

    import resume_agent.discovery.connectors.adzuna as mod

    monkeypatch.setattr(mod, "render_pages", fake_render_pages)
    jobs = [
        _raw(url="https://www.adzuna.com/jobs/1"),
        _raw(url="https://www.adzuna.com/jobs/2"),
    ]

    enriched, failures = enrich_adzuna_jobs(jobs)

    # One render pass for the whole batch, both urls handed in together.
    assert calls["urls"] == [
        "https://www.adzuna.com/jobs/1",
        "https://www.adzuna.com/jobs/2",
    ]
    assert "word79" in enriched[0].jd_text
    assert enriched[1].jd_text == "Short Python preview."  # no page -> snippet kept
    assert failures == {"https://www.adzuna.com/jobs/2": "render_failed"}


def test_enrich_jobs_falls_back_to_snippets_when_browser_unavailable(monkeypatch):
    def boom(urls):
        raise RuntimeError("no browser")

    import resume_agent.discovery.connectors.adzuna as mod

    monkeypatch.setattr(mod, "render_pages", boom)
    jobs = [_raw()]

    enriched, failures = enrich_adzuna_jobs(jobs)

    assert enriched is jobs  # contract: snippets intact, pull not aborted
    assert failures == {"adzuna": "RuntimeError"}
