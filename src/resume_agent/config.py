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
    cheap_model: str = "claude-haiku-4-5"
    mid_model: str = "claude-sonnet-5"
    premium_model: str = "claude-opus-5"
    cheap_reasoning_effort: str | None = None
    mid_reasoning_effort: str | None = None
    premium_reasoning_effort: str | None = None
    transcribe_model: str = "gemini:gemini-3.5-flash-lite"
    api_token: str = (
        ""  # when non-empty, the API requires Authorization: Bearer <token>
    )
    auth_username: str = ""
    auth_password_hash: str = ""
    session_secret: str = ""
    secure_cookies: bool = False
    allowed_hosts: str = ""
    disable_api_docs: bool = False
    registration_mode: Literal["closed", "invite", "open"] = "invite"
    global_daily_signup_limit: int = Field(default=50, ge=1)
    global_weekly_token_budget: int = Field(default=50_000_000, ge=0)
    open_signup_shared_keys: bool = False
    open_signup_weekly_token_budget: int = Field(default=250_000, ge=0)
    open_signup_max_active_jobs: int = Field(default=100, ge=0)
    open_signup_max_concurrent_runs: int = Field(default=1, ge=0)
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
    cluster_reconcile_batch_size: int = Field(default=150, ge=1, le=1000)
    domains_per_category_cap: int = Field(default=12, ge=3, le=15)
    search_mode: Literal["auto", "native", "tool", "off"] = "auto"
    advisor_model: str = ""

    # Gmail integration (platform OAuth client; users may override the client
    # via their workspace secrets.env — str fields join the overlay for free).
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    gmail_sync_interval_hours: int = Field(default=6, ge=0)  # 0 = scheduler off
    follow_up_days: int = Field(default=14, ge=0)  # 0 = reminders off
    gmail_max_messages: int = Field(default=50, ge=1)

    # Platform mail is process-level configuration. It is intentionally kept
    # outside the per-workspace secrets overlay used by Gmail.
    #
    # Two delivery backends: an HTTPS transactional API (Resend) and SMTP.
    # `resend_api_key` wins when both are set, because hosts that block
    # outbound SMTP -- Railway does so below the Pro plan, where port 587
    # fails with ENETUNREACH regardless of credentials -- leave HTTPS as the
    # only path that can work. `mail_from` is the backend-neutral sender and
    # falls back to `smtp_from` so an SMTP-era deploy needs no renaming.
    resend_api_key: str = ""
    mail_from: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    app_base_url: str = ""
    auth_email: str = ""


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
