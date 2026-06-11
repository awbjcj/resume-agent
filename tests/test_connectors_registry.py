from typing import Any, cast

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.registry import build_connectors


def _settings(**kwargs):
    settings_type = cast(Any, Settings)
    return settings_type(_env_file=None, **kwargs)


def _cfg(**enabled):
    data = {
        "greenhouse": {
            "enabled": enabled.get("greenhouse", False),
            "boards": [{"token": "stripe"}],
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
    cfg = _cfg(greenhouse=True, adzuna=True, remoteok=True, linkedin=True)
    settings = _settings(adzuna_app_id="x", adzuna_app_key="y")
    names = [c.name for c in build_connectors(cfg, settings)]
    assert names == ["greenhouse", "remoteok", "adzuna", "linkedin"]


def test_adzuna_skipped_without_credentials():
    cfg = _cfg(adzuna=True)
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == []
