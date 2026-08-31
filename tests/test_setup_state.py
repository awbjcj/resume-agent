from resume_tailor_harness.config import Settings
from resume_tailor_harness.setup.state import WizardState


def test_defaults_match_settings_defaults():
    # Compare against Settings rather than restating its literals. Restating them
    # is what let mid_model drift a generation behind (claude-sonnet-4-6 vs
    # claude-sonnet-5) while this test -- named for the invariant it was meant to
    # protect -- kept passing.
    s = WizardState()
    assert s.db_url == "sqlite:///data/resume_tailor_harness.db"
    for tier in ("cheap_model", "mid_model", "premium_model"):
        assert getattr(s, tier) == Settings.model_fields[tier].default
    assert s.remote_policy == "any"
    assert s.greenhouse_boards == []


def test_managed_env_omits_empty_and_maps_keys():
    s = WizardState(anthropic_api_key="sk-test", github_token="")
    env = s.managed_env()
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "GITHUB_TOKEN" not in env  # empty → omitted
    assert env["DB_URL"] == "sqlite:///data/resume_tailor_harness.db"
    assert "OPENAI_API_KEY" not in env  # never managed
