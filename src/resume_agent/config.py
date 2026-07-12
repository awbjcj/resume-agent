from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and environment-level config, loaded from ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    github_token: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""
    linkedin_user_data_dir: str = ".linkedin_profile"
    db_url: str = "sqlite:///data/resume_agent.db"
    cheap_model: str = "claude-haiku-4-5-20251001"
    mid_model: str = "claude-sonnet-5"
    premium_model: str = "claude-opus-4-8"
    api_token: str = (
        ""  # when non-empty, the API requires Authorization: Bearer <token>
    )
    auth_username: str = ""
    auth_password_hash: str = ""
    session_secret: str = ""
    browser_enabled: bool = True
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    # Concurrency + retry for LLM fan-out (discovery + tailor).
    llm_concurrency: int = Field(default=8, ge=1)
    pull_concurrency: int = Field(default=4, ge=1)
    llm_retries: int = Field(default=2, ge=0)
    llm_retry_delay: int = Field(default=1, ge=0)
    prompt_cache_enabled: bool = True
    suggestion_batch_concurrency: int = Field(default=3, ge=1, le=16)
    cluster_batch_size: int = Field(default=60, ge=1, le=500)
    search_mode: Literal["auto", "native", "tool", "off"] = "auto"
    advisor_model: str = ""


@lru_cache
def env_settings() -> Settings:
    """Cached process settings used when no tenant context is active."""
    return Settings()


def get_settings() -> Settings:
    """Return the active tenant's effective settings, else process settings."""
    from resume_agent.tenancy.context import current_context

    context = current_context()
    return context.settings if context is not None else env_settings()


# Compatibility for existing tests/callers while they migrate to env_settings.
get_settings.cache_clear = env_settings.cache_clear  # type: ignore[attr-defined]


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file, requiring a mapping at the top level."""
    from resume_agent.tenancy.paths import resolve_tenant_path

    p = resolve_tenant_path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a mapping at the top of {p}, got {type(data).__name__}"
        )
    return data
