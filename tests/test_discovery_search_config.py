from resume_agent.discovery.search_config import SearchConfig, load_search_config


def test_defaults_are_empty():
    cfg = SearchConfig()
    assert cfg.keywords == []
    assert cfg.sponsorship_required is False
    assert cfg.min_salary is None


def test_load_from_yaml(tmp_path):
    f = tmp_path / "search.yaml"
    f.write_text(
        "keywords:\n  - python\ntitles:\n  - Engineer\n"
        "min_salary: 120000\nyoe_max: 5\nsponsorship_required: true\n",
        encoding="utf-8",
    )
    cfg = load_search_config(f)
    assert cfg.keywords == ["python"]
    assert cfg.min_salary == 120000
    assert cfg.yoe_max == 5
    assert cfg.sponsorship_required is True
