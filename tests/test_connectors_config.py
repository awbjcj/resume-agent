from pathlib import Path

from resume_agent.discovery.connectors.config import ConnectorsConfig, load_connectors_config


def test_defaults_are_all_disabled():
    cfg = ConnectorsConfig()
    assert cfg.greenhouse.enabled is False
    assert cfg.lever.enabled is False
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
    cfg = ConnectorsConfig.model_validate({"greenhouse": {"boards": [{"token": "acme"}]}})
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
    assert cfg.companies.urls == ["https://careers.acme.com"]


def test_example_file_has_companies_section():
    cfg = load_connectors_config(Path("config/connectors.yaml.example"))
    assert cfg.companies.urls
