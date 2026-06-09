from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and environment-level config, loaded from ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    github_token: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""
    db_url: str = "sqlite:///data/resume_agent.db"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor used across the app."""
    return Settings()


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file, requiring a mapping at the top level."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at the top of {p}, got {type(data).__name__}")
    return data
