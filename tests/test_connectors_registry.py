from typing import Any, cast

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.registry import build_connectors, build_source_connectors


def _settings(**kwargs):
    settings_type = cast(Any, Settings)
    return settings_type(_env_file=None, **kwargs)


def _cfg(**enabled):
    data = {
        "greenhouse": {
            "enabled": enabled.get("greenhouse", False),
            "boards": [{"token": "stripe"}],
        },
        "lever": {
            "enabled": enabled.get("lever", False),
            "boards": [{"token": "palantir"}],
        },
        "adzuna": {"enabled": enabled.get("adzuna", False)},
        "remoteok": {"enabled": enabled.get("remoteok", False)},
        "linkedin": {"enabled": enabled.get("linkedin", False)},
    }
    return ConnectorsConfig.model_validate(data)


def test_only_enabled_connectors_are_built():
    cfg = _cfg(greenhouse=True, remoteok=True)
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == ["greenhouse", "remoteok"]


def test_canonical_order_is_ats_feed_aggregator_linkedin():
    cfg = _cfg(greenhouse=True, lever=True, adzuna=True, remoteok=True, linkedin=True)
    settings = _settings(adzuna_app_id="x", adzuna_app_key="y")
    names = [c.name for c in build_connectors(cfg, settings)]
    assert names == ["greenhouse", "lever", "remoteok", "adzuna", "linkedin"]


def test_lever_skipped_without_boards():
    cfg = ConnectorsConfig.model_validate({"lever": {"enabled": True, "boards": []}})
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == []


def test_adzuna_skipped_without_credentials():
    cfg = _cfg(adzuna=True)
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == []


def test_companies_connector_built_when_enabled_with_urls():
    cfg = ConnectorsConfig.model_validate(
        {"companies": {"enabled": True, "urls": ["https://jobs.ashbyhq.com/acme"]}}
    )
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == ["companies"]


def test_companies_skipped_when_enabled_without_urls():
    cfg = ConnectorsConfig.model_validate({"companies": {"enabled": True, "urls": []}})
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == []


def test_companies_ordered_with_ats_sources_before_aggregators():
    cfg = ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": True, "boards": [{"token": "stripe"}]},
            "lever": {"enabled": True, "boards": [{"token": "palantir"}]},
            "remoteok": {"enabled": True},
            "adzuna": {"enabled": True},
            "linkedin": {"enabled": True},
            "companies": {"enabled": True, "urls": ["https://jobs.ashbyhq.com/acme"]},
        }
    )
    settings = _settings(adzuna_app_id="x", adzuna_app_key="y")
    names = [c.name for c in build_connectors(cfg, settings)]
    assert names == ["greenhouse", "lever", "companies", "remoteok", "adzuna", "linkedin"]


def _full_cfg():
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {
                "enabled": True,
                "boards": [{"token": "anthropic"}, {"token": "scaleai", "enabled": False}],
            },
            "companies": {
                "enabled": True,
                "urls": [{"url": "https://jobs.ashbyhq.com/openai"}],
            },
            "remoteok": {"enabled": True},
            "adzuna": {"enabled": False},
            "linkedin": {"enabled": False},
        }
    )


def test_build_source_connectors_is_one_per_enabled_entry():
    names = [connector.name for connector in build_source_connectors(_full_cfg(), _settings())]
    assert names == [
        "greenhouse:anthropic",
        "companies:" + __import__("hashlib").sha1(b"https://jobs.ashbyhq.com/openai").hexdigest()[:8],
        "remoteok",
    ]


def test_build_source_connectors_honors_explicit_selection():
    names = [
        connector.name
        for connector in build_source_connectors(
            _full_cfg(), _settings(), source_ids=["remoteok"]
        )
    ]
    assert names == ["remoteok"]


def test_build_source_connectors_skips_adzuna_without_keys():
    cfg = ConnectorsConfig.model_validate(
        {
            "adzuna": {"enabled": True, "country": "us"},
            "remoteok": {"enabled": False},
            "linkedin": {"enabled": False},
        }
    )
    names = [connector.name for connector in build_source_connectors(cfg, _settings())]
    assert "adzuna" not in names
