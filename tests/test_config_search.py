import pytest
from pydantic import ValidationError

from resume_agent.config import Settings


def test_search_settings_defaults():
    settings = Settings(_env_file=None)

    assert settings.search_mode == "auto"
    assert settings.advisor_model == ""


def test_search_mode_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Settings(search_mode="typo", _env_file=None)
