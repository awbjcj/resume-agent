from typing import Any, cast

from resume_tailor_harness.config import Settings
from resume_tailor_harness.discovery.connectors.adzuna import AdzunaConnector
from resume_tailor_harness.discovery.connectors.companies import CompaniesConnector
from resume_tailor_harness.discovery.connectors.config import ConnectorsConfig
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.registry import (
    CONNECTOR_SPECS,
    build_connectors,
    build_source_connectors,
    find_unit,
    spec_for,
)
from resume_tailor_harness.discovery.connectors.remoteok import RemoteOKConnector
from resume_tailor_harness.discovery.scraper.linkedin import LinkedInScraper


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


def test_registry_threads_singleton_limits_to_connectors():
    cfg = ConnectorsConfig.model_validate(
        {
            "remoteok": {"enabled": True, "limit": 11},
            "adzuna": {"enabled": True, "limit": 12},
            "linkedin": {"enabled": True, "limit": 13},
        }
    )
    settings = _settings(adzuna_app_id="x", adzuna_app_key="y")
    connectors = {
        connector.name: connector for connector in build_connectors(cfg, settings)
    }
    remoteok = connectors["remoteok"]
    adzuna = connectors["adzuna"]
    linkedin = connectors["linkedin"]
    assert isinstance(remoteok, RemoteOKConnector)
    assert isinstance(adzuna, AdzunaConnector)
    assert isinstance(linkedin, LinkedInScraper)
    assert remoteok.configured_limit == 11
    assert adzuna.configured_limit == 12
    assert linkedin.configured_limit == 13


def test_companies_connector_built_when_enabled_with_urls():
    cfg = ConnectorsConfig.model_validate(
        {"companies": {"enabled": True, "urls": ["https://jobs.ashbyhq.com/acme"]}}
    )
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == ["companies"]


def test_url_based_native_connector_keeps_its_ats_identity():
    cfg = ConnectorsConfig.model_validate(
        {
            "workday": {
                "enabled": True,
                "boards": [
                    {
                        "url": "https://acme.wd5.myworkdayjobs.com/Careers",
                        "company": "Acme",
                    }
                ],
            }
        }
    )

    aggregate = build_connectors(cfg, _settings())
    per_source = build_source_connectors(cfg, _settings())

    assert [connector.name for connector in aggregate] == ["workday"]
    assert per_source[0].name.startswith("workday:")


def test_companies_registry_preserves_url_limit():
    cfg = ConnectorsConfig.model_validate(
        {
            "companies": {
                "enabled": True,
                "urls": [{"url": "https://jobs.ashbyhq.com/acme", "limit": 7}],
            }
        }
    )
    connector = build_connectors(cfg, _settings())[0]
    assert isinstance(connector, CompaniesConnector)
    assert connector.urls[0].limit == 7


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
    assert names == [
        "greenhouse",
        "lever",
        "companies",
        "remoteok",
        "adzuna",
        "linkedin",
    ]


def _full_cfg():
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {
                "enabled": True,
                "boards": [
                    {"token": "anthropic"},
                    {"token": "scaleai", "enabled": False},
                ],
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
    names = [
        connector.name
        for connector in build_source_connectors(_full_cfg(), _settings())
    ]
    assert names == [
        "greenhouse:anthropic",
        "companies:"
        + __import__("hashlib")
        .sha1(b"https://jobs.ashbyhq.com/openai")
        .hexdigest()[:8],
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


def test_spec_table_is_the_single_enumeration():
    kinds = [spec.kind for spec in CONNECTOR_SPECS]
    assert kinds == [
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "tesla",
        "google",
        "smartrecruiters",
        "workable",
        "recruitee",
        "personio",
        "breezy",
        "jazzhr",
        "bamboohr",
        "companies",
        "scrape",
        "remoteok",
        "adzuna",
        "linkedin",
    ]  # canonical dedup order
    assert len(set(kinds)) == len(kinds)


def _sample_config() -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": True, "boards": [{"token": "acme"}]},
            "lever": {"enabled": True, "boards": [{"token": "lev"}]},
            "ashby": {"enabled": True, "boards": [{"token": "ash"}]},
            "workday": {
                "enabled": True,
                "boards": [{"url": "https://acme.wd5.myworkdayjobs.com/External"}],
            },
            "companies": {
                "enabled": True,
                "urls": ["https://example.com/careers"],
            },
            "scrape": {
                "enabled": True,
                "targets": [{"url": "https://jobs.example.org/list"}],
            },
            "adzuna": {"enabled": True},
            "remoteok": {"enabled": True},
            "linkedin": {"enabled": True},
        }
    )


def test_find_unit_round_trips_every_unit():
    config = _sample_config()
    seen = 0
    for spec in CONNECTOR_SPECS:
        for unit in spec.units(config):
            found = find_unit(config, unit.source_id)
            assert found is not None, unit.source_id
            found_spec, payload = found
            assert found_spec.kind == spec.kind
            assert payload is unit.payload
            seen += 1
    assert seen >= 9


def test_find_unit_unknown_id_returns_none():
    assert find_unit(_sample_config(), "greenhouse:nope") is None


def test_every_spec_addresses_a_section_with_enabled():
    config = ConnectorsConfig()
    for spec in CONNECTOR_SPECS:
        assert hasattr(spec.section(config), "enabled"), spec.kind


def test_new_unit_produces_addressable_units():
    config = ConnectorsConfig()
    cases = {
        "greenhouse": (
            AtsTarget(ats="greenhouse", token="acme"),
            "https://job-boards.greenhouse.io/acme",
        ),
        "workday": (
            AtsTarget(ats="workday", tenant="acme", datacenter="wd5", site="Ext"),
            "https://acme.wd5.myworkdayjobs.com/Ext",
        ),
        "companies": (AtsTarget(ats="companies"), "https://example.com/careers"),
        "scrape": (None, "https://jobs.example.org/list"),
    }
    for kind, (target, url) in cases.items():
        spec = spec_for(kind)
        assert spec is not None and spec.new_unit is not None
        assert spec.unit_items is not None
        source_id, payload = spec.new_unit(target, url, "Label")
        spec.unit_items(config).append(payload)
        assert any(unit.source_id == source_id for unit in spec.units(config)), kind


def test_token_kinds_admit_only_tokened_targets():
    spec = spec_for("greenhouse")
    assert spec is not None
    assert spec.admits(AtsTarget(ats="greenhouse", token="acme"))
    assert not spec.admits(AtsTarget(ats="greenhouse"))
