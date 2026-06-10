import pytest

from resume_agent.config import Settings, load_yaml


def test_settings_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-test\nGITHUB_TOKEN=ghp-test\n", encoding="utf-8")
    settings = Settings(_env_file=str(env))
    assert settings.anthropic_api_key == "sk-test"
    assert settings.github_token == "ghp-test"


def test_settings_have_safe_defaults():
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key == ""
    assert settings.linkedin_user_data_dir == ".linkedin_profile"
    assert settings.db_url.startswith("sqlite:///")


def test_load_yaml_parses_mapping(tmp_path):
    f = tmp_path / "search.yaml"
    f.write_text("keywords:\n  - python\n  - backend\nsponsorship_required: true\n", encoding="utf-8")
    data = load_yaml(f)
    assert data["keywords"] == ["python", "backend"]
    assert data["sponsorship_required"] is True


def test_load_yaml_rejects_non_mapping(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_yaml(f)


def test_settings_has_cheap_model_default():
    settings = Settings(_env_file=None)
    assert settings.cheap_model == "claude-haiku-4-5-20251001"


def test_settings_has_model_tier_defaults():
    settings = Settings(_env_file=None)
    assert settings.mid_model == "claude-sonnet-4-6"
    assert settings.premium_model == "claude-opus-4-8"
