from resume_agent.setup.state import WizardState


def test_defaults_match_settings_defaults():
    s = WizardState()
    assert s.db_url == "sqlite:///data/resume_agent.db"
    assert s.cheap_model == "claude-haiku-4-5-20251001"
    assert s.remote_policy == "any"
    assert s.greenhouse_boards == []


def test_managed_env_omits_empty_and_maps_keys():
    s = WizardState(anthropic_api_key="sk-test", github_token="")
    env = s.managed_env()
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "GITHUB_TOKEN" not in env          # empty → omitted
    assert env["DB_URL"] == "sqlite:///data/resume_agent.db"
    assert "OPENAI_API_KEY" not in env         # never managed
