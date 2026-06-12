from pathlib import Path

from resume_agent.discovery.connectors.config import ConnectorsConfig, load_connectors_config


def test_defaults_are_all_disabled():
    cfg = ConnectorsConfig()
    assert cfg.greenhouse.enabled is False
    assert cfg.adzuna.enabled is False
    assert cfg.remoteok.enabled is False
    assert cfg.linkedin.enabled is False


def test_loads_example_file():
    example = Path("config/connectors.yaml.example")
    cfg = load_connectors_config(example)
    assert cfg.greenhouse.enabled is True
    assert cfg.greenhouse.boards[0].token == "stripe"
    assert cfg.adzuna.country == "us"


def test_board_company_defaults_to_token():
    cfg = ConnectorsConfig.model_validate({"greenhouse": {"boards": [{"token": "acme"}]}})
    board = cfg.greenhouse.boards[0]
    assert board.company is None
    assert board.display() == "acme"
