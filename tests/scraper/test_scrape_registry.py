from typing import Any, cast

import pytest
from pydantic import ValidationError

from resume_tailor_harness.config import Settings
from resume_tailor_harness.discovery.connectors.config import (
    ConnectorsConfig,
    ScrapeConfig,
    ScrapeTarget,
)
from resume_tailor_harness.discovery.connectors.registry import (
    build_connectors,
    build_source_connectors,
)
from resume_tailor_harness.discovery.scraper.dashboard import DashboardScraper


def _settings():
    return cast(Any, Settings)(_env_file=None)


def test_scrape_connector_built_when_enabled():
    config = ConnectorsConfig(
        scrape=ScrapeConfig(
            enabled=True,
            targets=[ScrapeTarget(url="https://acme.com/careers", label="Acme")],
        )
    )
    connectors = build_connectors(config, _settings())
    assert [connector.name for connector in connectors] == ["scrape"]
    assert isinstance(connectors[0], DashboardScraper)


def test_scrape_connector_absent_when_disabled_or_empty():
    disabled = ConnectorsConfig(
        scrape=ScrapeConfig(
            enabled=False,
            targets=[ScrapeTarget(url="https://acme.com/careers")],
        )
    )
    empty = ConnectorsConfig(scrape=ScrapeConfig(enabled=True))
    assert not any(
        isinstance(item, DashboardScraper)
        for item in build_connectors(disabled, _settings())
    )
    assert not any(
        isinstance(item, DashboardScraper)
        for item in build_connectors(empty, _settings())
    )


def test_scrape_target_accepts_bare_string_and_validates_http_url():
    config = ConnectorsConfig.model_validate(
        {"scrape": {"enabled": True, "targets": ["https://acme.com/careers"]}}
    )
    assert config.scrape.targets[0].url == "https://acme.com/careers"
    with pytest.raises(ValidationError, match="http"):
        ScrapeTarget(url="file:///tmp/jobs.html")


def test_scrape_config_rejects_duplicate_recipe_hosts():
    with pytest.raises(ValidationError, match="one target per host"):
        ScrapeConfig(
            enabled=True,
            targets=[
                ScrapeTarget(url="https://acme.com/careers"),
                ScrapeTarget(url="https://www.acme.com/jobs"),
            ],
        )


def test_source_registry_builds_one_selectable_connector_per_host():
    config = ConnectorsConfig(
        scrape=ScrapeConfig(
            enabled=True,
            targets=[ScrapeTarget(url="https://careers.acme.com/jobs")],
        )
    )
    connectors = build_source_connectors(
        config,
        _settings(),
        source_ids=["scrape:careers.acme.com"],
    )
    assert len(connectors) == 1
    assert connectors[0].name == "scrape:careers.acme.com"
    assert isinstance(connectors[0], DashboardScraper)
