"""Write-only secrets contract + readable model-tier config."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel

# schema field name -> .env variable. One place; GET, PUT, and setup-status use it.
SECRET_FIELDS: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "github_token": "GITHUB_TOKEN",
    "adzuna_app_id": "ADZUNA_APP_ID",
    "adzuna_app_key": "ADZUNA_APP_KEY",
    "linkedin_email": "LINKEDIN_EMAIL",
    "linkedin_password": "LINKEDIN_PASSWORD",
    "google_oauth_client_id": "GOOGLE_OAUTH_CLIENT_ID",
    "google_oauth_client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
}

# Any one of these satisfies "an LLM key is configured" — profile build and
# tailoring pick a provider via Settings.mid_model (see llm_runner.split_provider),
# so the gate isn't specific to Anthropic.
LLM_KEY_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
)


class SecretStatus(CamelModel):
    key: str  # camelCase field name, e.g. "anthropicApiKey"
    is_set: bool
    hint: str | None = None  # last 4 chars, only when len(value) >= 8


class SecretsUpdate(CamelModel):
    """All-optional; only fields present in the request body are written.
    An explicit null clears the key."""

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    deepseek_api_key: str | None = None
    github_token: str | None = None
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    linkedin_email: str | None = None
    linkedin_password: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None


class ModelsConfigDoc(CamelModel):
    cheap_model: str = "claude-haiku-4-5-20251001"
    mid_model: str = "claude-sonnet-5"
    premium_model: str = "claude-opus-4-8"
    cheap_reasoning_effort: str | None = None
    mid_reasoning_effort: str | None = None
    premium_reasoning_effort: str | None = None
    cheap_response_verbosity: str | None = None
    mid_response_verbosity: str | None = None
    premium_response_verbosity: str | None = None


class ModelOption(CamelModel):
    id: str
    label: str
    supports_reasoning: bool
    supports_native_search: bool
    reasoning_efforts: list[str]
    response_verbosity_levels: list[str]


class ProviderModelCatalog(CamelModel):
    provider: str
    label: str
    has_key: bool
    models: list[ModelOption]
