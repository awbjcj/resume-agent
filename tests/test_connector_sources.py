from typing import Any, cast

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.sources import (
    SourceView,
    company_url_id,
    list_source_views,
    scrape_target_id,
)


def _settings(**kwargs):
    settings_type = cast(Any, Settings)
    return settings_type(_env_file=None, **kwargs)


def _cfg():
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {
                "enabled": True,
                "boards": [{"token": "anthropic", "company": "Anthropic"}],
            },
            "lever": {
                "enabled": True,
                "boards": [{"token": "zoox", "company": "Zoox", "enabled": False}],
            },
            "ashby": {
                "enabled": True,
                "boards": [{"token": "openai", "company": "OpenAI"}],
            },
            "companies": {
                "enabled": True,
                "urls": [{"url": "https://jobs.ashbyhq.com/openai", "label": "OpenAI"}],
            },
            "adzuna": {"enabled": True, "country": "us"},
            "remoteok": {"enabled": True},
            "linkedin": {"enabled": False},
            "scrape": {
                "enabled": True,
                "targets": [
                    {
                        "url": "https://careers.example/jobs",
                        "label": "Example",
                        "limit": 6,
                    }
                ],
            },
        }
    )


def test_company_url_id_is_stable_and_prefixed():
    assert company_url_id("https://x.co").startswith("companies:")
    assert company_url_id("https://x.co") == company_url_id("https://x.co")


def test_scrape_target_id_is_stable_and_matches_registry_shape():
    assert scrape_target_id("https://jobs.example/careers") == "scrape:jobs.example"


def test_list_source_views_covers_boards_and_aggregators():
    views = list_source_views(_cfg(), _settings(adzuna_app_id="a", adzuna_app_key="b"))
    by_id = {view.id: view for view in views}

    assert by_id["greenhouse:anthropic"] == SourceView(
        id="greenhouse:anthropic",
        kind="greenhouse",
        type="board",
        display_name="Anthropic",
        enabled=True,
        pullable=True,
        detail="anthropic",
    )
    assert by_id["lever:zoox"].enabled is False
    assert by_id["ashby:openai"].display_name == "OpenAI"
    assert by_id["ashby:openai"].detail == "openai"
    company_id = company_url_id("https://jobs.ashbyhq.com/openai")
    assert by_id[company_id].kind == "ashby"
    assert by_id[company_id].display_name == "OpenAI"
    assert by_id[company_id].detail == "openai"
    assert by_id["adzuna"].type == "aggregator"
    assert "key set" in by_id["adzuna"].detail
    assert by_id["adzuna"].pullable is True
    assert by_id["remoteok"].type == "aggregator"
    assert by_id["linkedin"].enabled is False
    assert by_id["linkedin"].pullable is False
    scrape = by_id[scrape_target_id("https://careers.example/jobs")]
    assert scrape.kind == "scrape"
    assert scrape.display_name == "Example"
    assert scrape.limit == 6


def test_source_views_project_configured_limits():
    cfg = ConnectorsConfig.model_validate(
        {
            "greenhouse": {
                "enabled": True,
                "boards": [{"token": "acme", "limit": 3}],
            },
            "remoteok": {"enabled": True, "limit": 4},
        }
    )
    views = {view.id: view for view in list_source_views(cfg, _settings())}
    assert views["greenhouse:acme"].limit == 3
    assert views["remoteok"].limit == 4


def test_adzuna_without_keys_is_enabled_but_not_pullable():
    views = list_source_views(_cfg(), _settings())
    adzuna = next(view for view in views if view.id == "adzuna")
    assert adzuna.enabled is True
    assert adzuna.pullable is False
    assert "no API key" in adzuna.detail


def test_board_sources_are_disabled_when_parent_group_is_disabled():
    cfg = ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": False, "boards": [{"token": "anthropic"}]},
            "lever": {"enabled": False, "boards": [{"token": "zoox"}]},
            "companies": {
                "enabled": False,
                "urls": [{"url": "https://jobs.ashbyhq.com/openai"}],
            },
        }
    )
    views = {view.id: view for view in list_source_views(cfg, _settings())}

    assert views["greenhouse:anthropic"].enabled is False
    assert views["greenhouse:anthropic"].pullable is False
    assert views["lever:zoox"].enabled is False
    assert views["lever:zoox"].pullable is False
    company_id = company_url_id("https://jobs.ashbyhq.com/openai")
    assert views[company_id].enabled is False
    assert views[company_id].pullable is False
