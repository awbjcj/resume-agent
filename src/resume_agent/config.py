from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

AppMode = Literal["local", "hosted"]

# Where one provider's traffic goes. "auto" resolves to "subscription" when a
# sub2api key is configured for that provider and "api" otherwise; the other
# two are an admin's explicit override. Defined here rather than in
# ``llm_routing`` so ``Settings`` can annotate its fields without importing a
# module that itself needs ``Settings``.
RouteMode = Literal["auto", "subscription", "api"]


class Settings(BaseSettings):
    """Secrets and environment-level config, loaded from ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_api_key: str = ""
    deepseek_api_key: str = ""

    # -- subscription routing (see llm_routing.py) --------------------------
    # One sub2api gateway, one key per provider, and a per-provider mode. The
    # gateway speaks each provider's native wire format at its own path, so a
    # single base URL serves all four; llm_routing derives the per-SDK suffix.
    sub2api_base_url: str = ""
    sub2api_anthropic_key: str = ""
    sub2api_openai_key: str = ""
    sub2api_gemini_key: str = ""
    sub2api_deepseek_key: str = ""
    # "auto" means subscription when that provider has a gateway key, else the
    # direct API. It is the default because it makes the fallback a property of
    # configuration -- a provider with no subscription simply has no key -- so
    # no call site needs to special-case DeepSeek or Gemini.
    anthropic_route_mode: RouteMode = "auto"
    openai_route_mode: RouteMode = "auto"
    gemini_route_mode: RouteMode = "auto"
    deepseek_route_mode: RouteMode = "auto"
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
    speech_model: str = "openai:gpt-4o-mini-tts"
    speech_voice: str = "marin"
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
    cost_quota_enforcement: Literal["shadow", "enforce"] = "shadow"
    # How long one SpendGate decision stays good. Budget is a property of a
    # phase, not of a call: re-deriving it per call cost ~22 statements each.
    # A long fan-out still re-checks periodically, so a budget exhausted
    # mid-run is noticed within this window (and immediately if a charge
    # exhausts the allowance, which invalidates the decision outright).
    spend_gate_ttl_seconds: float = Field(default=30.0, ge=0.0)
    global_monthly_cost_quota_micros: int = Field(default=500_000_000, ge=0)
    open_signup_weekly_token_budget: int = Field(default=250_000, ge=0)
    open_signup_max_active_jobs: int = Field(default=100, ge=0)
    open_signup_max_concurrent_runs: int = Field(default=1, ge=0)
    browser_enabled: bool = True
    stream_enabled: bool = True
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    # Concurrency + retry for LLM fan-out (discovery + tailor).
    llm_concurrency: int = Field(default=8, ge=1)
    pull_concurrency: int = Field(default=4, ge=1)
    # Per-host bound on the list-then-detail fan-out. Kept modest so a
    # concurrent detail pass does not turn a board's 429 retry into a
    # thundering herd.
    detail_fetch_concurrency: int = Field(default=4, ge=1)
    llm_retries: int = Field(default=2, ge=0)
    llm_retry_delay: int = Field(default=1, ge=0)
    # How recently a terminal run must have finished to still be worth
    # announcing when a client reconnects. Beyond this it is stale news; the
    # record stays readable until the 24h run sweep either way.
    run_announce_window_seconds: int = Field(default=3600, ge=0, le=86_400)
    prompt_cache_enabled: bool = True
    suggestion_batch_concurrency: int = Field(default=3, ge=1, le=16)
    cluster_batch_size: int = Field(default=60, ge=1, le=500)
    cluster_reconcile_batch_size: int = Field(default=150, ge=1, le=1000)
    # A soft organizational target.  ``DOMAINS_PER_CATEGORY_CAP`` remains an
    # accepted environment alias for one compatibility release, but taxonomy
    # admission no longer rejects a coherent new domain merely because the
    # category already has this many domains.
    domains_per_category_target: int = Field(
        default=12,
        ge=3,
        le=50,
        validation_alias=AliasChoices(
            "DOMAINS_PER_CATEGORY_TARGET", "DOMAINS_PER_CATEGORY_CAP"
        ),
    )
    skill_embedding_model: str = "openai:text-embedding-3-small"
    # The embedding endpoint accepts larger inputs, but keeping this bounded
    # makes the request behavior predictable and matches the taxonomy cache
    # transaction size.  ``cached_embeddings`` also clamps injected callers
    # defensively so a hand-built Settings object cannot exceed this limit.
    skill_embedding_batch_size: int = Field(default=256, ge=1, le=256)
    taxonomy_maintenance_max_churn: float = Field(default=0.20, ge=0.01, le=1.0)
    # Skills a first classification pass could not place are retried against the
    # whole taxonomy with the premium model.  That is deliberately the expensive
    # path, so it is bounded per run; anything past the bound keeps its recorded
    # status and escalates on the next run, which still converges.
    taxonomy_escalation_max_skills: int = Field(default=300, ge=0, le=5000)
    # Bounds the terminal singleton repair round.  In the normal case it is
    # never reached -- that round only ever sees the residue of a residue.  It
    # exists for the systematic-failure case (a bad prompt edit, a schema
    # mismatch) where every token fails every round and would otherwise
    # dispatch one call per token.  Overflow goes to the identity backstop,
    # which is safe by construction.
    taxonomy_canonical_repair_max_singletons: int = Field(
        default=500, ge=0, le=5000
    )
    # Every demanded skill ends a refresh with a home.  Disable only to restore
    # the historical behaviour where an uncertain skill stays unassigned.
    taxonomy_placement_floor: bool = True
    search_mode: Literal["auto", "native", "tool", "off"] = "auto"
    advisor_model: str = ""
    career_skill_root: Path = Path("skills")
    career_skill_manifest: Path = Path("skills-lock.json")
    h1b_mcp_enabled: bool = False
    h1b_mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    h1b_mcp_command: str = ""
    h1b_mcp_url: str = ""
    h1b_mcp_timeout_seconds: int = Field(default=30, ge=1, le=300)
    h1b_mcp_max_result_chars: int = Field(default=200_000, ge=1_000, le=1_000_000)
    h1b_cache_ttl_days: int = Field(default=30, ge=1, le=365)
    h1b_enrich_max_companies_per_run: int = Field(default=50, ge=0)

    @model_validator(mode="after")
    def validate_h1b_transport(self) -> Settings:
        if not self.h1b_mcp_enabled:
            return self
        command = self.h1b_mcp_command.strip()
        url = self.h1b_mcp_url.strip()
        if self.h1b_mcp_transport == "stdio":
            if not command or url:
                raise ValueError(
                    "enabled H1B stdio transport requires command and no URL"
                )
            return self
        if command or not url:
            raise ValueError(
                "enabled H1B streamable-http transport requires URL and no command"
            )
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("H1B MCP URL must be an absolute HTTP(S) URL with a host")
        if parsed.username or parsed.password:
            raise ValueError("H1B MCP URL must not contain credentials")
        return self

    # Gmail integration (platform OAuth client; users may override the client
    # via their workspace secrets.env — str fields join the overlay for free).
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    gmail_sync_interval_hours: int = Field(default=6, ge=0)  # 0 = scheduler off
    follow_up_days: int = Field(default=14, ge=0)  # 0 = reminders off
    gmail_max_messages: int = Field(default=50, ge=1)

    @property
    def domains_per_category_cap(self) -> int:
        """Compatibility alias for callers not yet migrated to the soft target."""

        return self.domains_per_category_target

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
