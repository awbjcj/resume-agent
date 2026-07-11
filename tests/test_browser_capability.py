from resume_agent.config import Settings
from resume_agent.discovery.connectors import companies as companies_module
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.registry import build_source_connectors
from resume_agent.discovery.search_config import SearchConfig

REASON = "requires a local browser (browser_enabled=false)"


def _settings(**updates) -> Settings:
    return Settings(_env_file=None, **updates)  # type: ignore[call-arg]


def _config() -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(
        {
            "scrape": {
                "enabled": True,
                "targets": [{"url": "https://example.test/jobs"}],
            },
            "linkedin": {"enabled": True},
            "adzuna": {"enabled": True},
            "companies": {
                "enabled": True,
                "urls": [{"url": "https://boards.greenhouse.io/acme"}],
            },
        }
    )


def test_registry_reports_disabled_browser_sources_instead_of_dropping_them():
    connectors = build_source_connectors(
        _config(),
        _settings(
            browser_enabled=False,
            adzuna_app_id="id",
            adzuna_app_key="key",
        ),
    )
    by_name = {connector.name: connector for connector in connectors}

    scrape = by_name[next(name for name in by_name if name.startswith("scrape:"))]
    linkedin = by_name["linkedin"]
    assert list(scrape.fetch(SearchConfig()).failures.values()) == [REASON]
    assert linkedin.fetch(SearchConfig()).failures == {"linkedin": REASON}
    adzuna = by_name["adzuna"]
    assert adzuna.enrich_details is False


def test_companies_tesla_isolated_when_browser_disabled(monkeypatch):
    greenhouse_job = RawJob(
        source="greenhouse",
        url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme",
        title="Engineer",
        location="",
        jd_text="description",
    )
    monkeypatch.setitem(
        companies_module._BACKENDS,
        "greenhouse",
        lambda target, search, limit=None, skip_seen=None: [greenhouse_job],
    )
    connector = CompaniesConnector(
        [
            "https://www.tesla.com/careers/search",
            "https://boards.greenhouse.io/acme",
        ],
        browser_enabled=False,
    )

    result = connector.fetch(SearchConfig())

    assert result.failures["https://www.tesla.com/careers/search"] == REASON
    assert [job.url for job in result.jobs] == [greenhouse_job.url]


def test_url_ingest_ands_caller_flag_with_browser_setting(monkeypatch):
    from resume_agent.services import discovery

    seen = {}
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(
        discovery,
        "get_settings",
        lambda: _settings(browser_enabled=False),
    )
    monkeypatch.setattr(
        discovery,
        "job_from_url",
        lambda url, *, agent, allow_browser: seen.update(allow_browser=allow_browser),
    )

    try:
        discovery.add_job_from_url(None, url="https://example.test/job")
    except discovery.UrlFetchError:
        pass

    assert seen["allow_browser"] is False


def test_linkedin_service_returns_explicit_failure_without_building_scraper(monkeypatch):
    from resume_agent.services import discovery

    monkeypatch.setattr(
        discovery,
        "get_settings",
        lambda: _settings(browser_enabled=False),
    )
    monkeypatch.setattr(
        discovery,
        "build_linkedin_scraper",
        lambda: (_ for _ in ()).throw(AssertionError("browser scraper constructed")),
    )

    assert discovery.scrape_linkedin_jobs(None) == {
        "added": 0,
        "failures": {"linkedin": REASON},
    }
