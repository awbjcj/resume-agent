import pytest
from pydantic import ValidationError
from typing import Any, cast

from resume_tailor_harness.config import Settings


def _settings(**kwargs) -> Settings:
    settings_type = cast(Any, Settings)
    return settings_type(_env_file=None, **kwargs)


def test_search_settings_defaults():
    settings = _settings()

    assert settings.search_mode == "auto"
    assert settings.advisor_model == ""


def test_search_mode_rejects_unknown_value():
    with pytest.raises(ValidationError):
        _settings(search_mode="typo")
