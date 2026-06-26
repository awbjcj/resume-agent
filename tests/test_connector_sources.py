from typing import Any, cast

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.sources import (
    SourceView,
    company_url_id,
    list_source_views,
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
            "companies": {
                "enabled": True,
                "urls": [{"url": "https://jobs.ashbyhq.com/openai", "label": "OpenAI"}],
            },
            "adzuna": {"enabled": True, "country": "us"},
            "remoteok": {"enabled": True},
            "linkedin": {"enabled": False},
        }
    )


def test_company_url_id_is_stable_and_prefixed():
    assert company_url_id("https://x.co").startswith("companies:")
    assert company_url_id("https://x.co") == company_url_id("https://x.co")


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
    company_id = company_url_id("https://jobs.ashbyhq.com/openai")
    assert by_id[company_id].kind == "ashby"
    assert by_id[company_id].display_name == "OpenAI"
    assert by_id["adzuna"].type == "aggregator"
    assert "key set" in by_id["adzuna"].detail
    assert by_id["adzuna"].pullable is True
    assert by_id["remoteok"].type == "aggregator"
    assert by_id["linkedin"].enabled is False
    assert by_id["linkedin"].pullable is False


def test_adzuna_without_keys_is_enabled_but_not_pullable():
    views = list_source_views(_cfg(), _settings())
    adzuna = next(view for view in views if view.id == "adzuna")
    assert adzuna.enabled is True
    assert adzuna.pullable is False
    assert "no API key" in adzuna.detail
