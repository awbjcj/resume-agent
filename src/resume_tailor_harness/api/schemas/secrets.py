"""Write-only secrets contract + readable model-tier config."""

from __future__ import annotations

from typing import cast

from resume_tailor_harness.api.schemas.base import CamelModel
from resume_tailor_harness.config import Settings


def _tier_default(field: str) -> str:
    """Read a model-tier default off ``Settings`` instead of restating it.

    These defaults used to be duplicated as literals here and in the setup
    wizard, which is how the wizard silently drifted a generation behind
    ``Settings``. Deriving them keeps the API docs, the wizard, and the runtime
    honest, and makes the OpenAPI contract move whenever a tier default moves.
    """
    return cast(str, Settings.model_fields[field].default)


# schema field name -> .env variable. One place for the write-only secrets API.
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
    cheap_model: str = _tier_default("cheap_model")
    mid_model: str = _tier_default("mid_model")
    premium_model: str = _tier_default("premium_model")
    cheap_reasoning_effort: str | None = None
    mid_reasoning_effort: str | None = None
    premium_reasoning_effort: str | None = None


class ModelOption(CamelModel):
    id: str
    label: str
    supports_reasoning: bool
    supports_native_search: bool
    reasoning_efforts: list[str]


class ProviderModelCatalog(CamelModel):
    provider: str
    label: str
    has_key: bool
    models: list[ModelOption]
