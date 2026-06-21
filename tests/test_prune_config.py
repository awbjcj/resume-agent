from resume_agent.tracking.prune_config import PruneConfig, load_prune_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_prune_config(tmp_path / "nope.yaml")
    assert cfg.fit_threshold == 40
    assert cfg.stale_days == 60
    assert cfg.retention_days == 30
    assert cfg.enable_rejected is True
    assert cfg.enable_low_fit is True
    assert cfg.enable_stale is True


def test_loads_overrides_from_yaml(tmp_path):
    path = tmp_path / "prune.yaml"
    path.write_text("fit_threshold: 55\nenable_stale: false\n", encoding="utf-8")
    cfg = load_prune_config(path)
    assert cfg.fit_threshold == 55
    assert cfg.enable_stale is False
    assert cfg.stale_days == 60  # untouched default


def test_is_a_pydantic_model_copy_updates():
    cfg = PruneConfig().model_copy(update={"fit_threshold": 10})
    assert cfg.fit_threshold == 10
