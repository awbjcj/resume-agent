from pathlib import Path

import pytest
from pydantic import ValidationError

from resume_tailor_harness.discovery.connectors.config import (
    AdzunaConfig,
    AshbyBoard,
    CompaniesConfig,
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    GreenhouseConfig,
    LeverBoard,
    LinkedInConfig,
    RemoteOKConfig,
    ScrapeTarget,
    load_connectors_config,
)


def test_defaults_are_all_disabled():
    cfg = ConnectorsConfig()
    assert cfg.greenhouse.enabled is False
    assert cfg.lever.enabled is False
    assert cfg.ashby.enabled is False
    assert cfg.adzuna.enabled is False
    assert cfg.remoteok.enabled is False
    assert cfg.linkedin.enabled is False
    assert cfg.companies.enabled is False


def test_loads_example_file():
    example = Path("config/connectors.yaml.example")
    cfg = load_connectors_config(example)
    assert cfg.greenhouse.enabled is True
    assert cfg.greenhouse.boards[0].token == "stripe"
    assert cfg.lever.enabled is True
    assert cfg.lever.boards[0].token == "palantir"
    assert cfg.adzuna.country == "us"


def test_lever_board_company_defaults_to_token():
    cfg = ConnectorsConfig.model_validate({"lever": {"boards": [{"token": "acme"}]}})
    board = cfg.lever.boards[0]
    assert board.company is None
    assert board.display() == "acme"


def test_board_company_defaults_to_token():
    cfg = ConnectorsConfig.model_validate(
        {"greenhouse": {"boards": [{"token": "acme"}]}}
    )
    board = cfg.greenhouse.boards[0]
    assert board.company is None
    assert board.display() == "acme"


def test_companies_defaults_to_disabled_empty():
    cfg = ConnectorsConfig()
    assert cfg.companies.enabled is False
    assert cfg.companies.urls == []


def test_companies_loads_urls():
    cfg = ConnectorsConfig.model_validate(
        {"companies": {"enabled": True, "urls": ["https://careers.acme.com"]}}
    )
    assert cfg.companies.enabled is True
    assert cfg.companies.urls == [CompanyUrl(url="https://careers.acme.com")]


def test_example_file_uses_native_sections_and_keeps_companies_for_backcompat():
    cfg = load_connectors_config(Path("config/connectors.yaml.example"))
    assert cfg.workday.boards
    assert cfg.tesla.boards
    assert cfg.google.boards
    assert cfg.companies.urls == []


def test_company_url_accepts_bare_string_for_backcompat():
    cfg = CompaniesConfig.model_validate({"enabled": True, "urls": ["https://x.co"]})
    assert cfg.urls == [CompanyUrl(url="https://x.co", enabled=True, label=None)]


def test_company_url_accepts_object_form():
    cfg = CompaniesConfig.model_validate(
        {
            "enabled": True,
            "urls": [{"url": "https://x.co", "enabled": False, "label": "X"}],
        }
    )
    assert cfg.urls[0].enabled is False
    assert cfg.urls[0].label == "X"


def test_board_enabled_defaults_true_when_absent():
    cfg = GreenhouseConfig.model_validate(
        {"enabled": True, "boards": [{"token": "anthropic"}]}
    )
    assert cfg.boards[0].enabled is True


def test_unit_models_accept_optional_positive_limits():
    assert GreenhouseBoard(token="acme").limit is None
    assert GreenhouseBoard(token="acme", limit=10).limit == 10
    assert LeverBoard(token="acme", limit=9).limit == 9
    assert AshbyBoard(token="acme", limit=8).limit == 8
    assert CompanyUrl(url="https://x.example/careers", limit=5).limit == 5
    assert ScrapeTarget(url="https://x.example/careers", limit=4).limit == 4


def test_singleton_sections_accept_optional_limits():
    config = ConnectorsConfig.model_validate(
        {"remoteok": {"limit": 25}, "adzuna": {"limit": 15}}
    )
    assert config.remoteok.limit == 25
    assert config.adzuna.limit == 15
    assert config.linkedin.limit is None


@pytest.mark.parametrize(
    "model",
    [
        lambda: GreenhouseBoard(token="acme", limit=0),
        lambda: LeverBoard(token="acme", limit=-1),
        lambda: AshbyBoard(token="acme", limit=0),
        lambda: CompanyUrl(url="https://x.example", limit=0),
        lambda: ScrapeTarget(url="https://x.example", limit=0),
        lambda: RemoteOKConfig(limit=0),
        lambda: AdzunaConfig(limit=0),
        lambda: LinkedInConfig(limit=0),
    ],
)
def test_limits_must_be_positive(model):
    with pytest.raises(ValidationError):
        model()


def test_bare_string_company_urls_still_coerce_with_no_limit():
    config = CompaniesConfig.model_validate({"urls": ["https://x.example/careers"]})
    assert config.urls[0].url == "https://x.example/careers"
    assert config.urls[0].limit is None
