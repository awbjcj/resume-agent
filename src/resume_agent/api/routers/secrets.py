"""Write-only secrets + readable model tiers, both backed by .env."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic.alias_generators import to_camel

from resume_agent.api.deps import get_env_path, refresh_app_settings
from resume_agent.api.schemas.secrets import (
    SECRET_FIELDS,
    ModelOption,
    ModelsConfigDoc,
    ProviderModelCatalog,
    SecretStatus,
    SecretsUpdate,
)
from resume_agent.llm_runner import (
    MODEL_CATALOG,
    PROVIDER_LABELS,
    provider_capabilities,
    supports_native_search,
)
from resume_agent.services.env_config import read_env, write_env_updates

router = APIRouter()

_MODEL_ENV = {
    "cheap_model": "CHEAP_MODEL",
    "mid_model": "MID_MODEL",
    "premium_model": "PREMIUM_MODEL",
}

_PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def _statuses(env_path) -> list[SecretStatus]:
    env = read_env(env_path)
    out = []
    for field, var in SECRET_FIELDS.items():
        value = env.get(var, "")
        hint = value[-4:] if len(value) >= 8 else None
        out.append(SecretStatus(key=to_camel(field), is_set=bool(value), hint=hint))
    return out


@router.get("/secrets", response_model=list[SecretStatus])
def get_secrets(request: Request):
    return _statuses(get_env_path(request))


@router.put("/secrets", response_model=list[SecretStatus])
def put_secrets(body: SecretsUpdate, request: Request):
    provided = body.model_dump(exclude_unset=True)
    updates = {SECRET_FIELDS[f]: (v or "") for f, v in provided.items()}
    env_path = get_env_path(request)
    fresh = write_env_updates(updates, env_path)
    refresh_app_settings(request.app, fresh)
    return _statuses(env_path)


@router.get("/config/models", response_model=ModelsConfigDoc)
def get_models(request: Request):
    env = read_env(get_env_path(request))
    defaults = ModelsConfigDoc()
    return ModelsConfigDoc(
        **{f: env.get(var) or getattr(defaults, f) for f, var in _MODEL_ENV.items()}
    )


@router.get("/config/models/catalog", response_model=list[ProviderModelCatalog])
def get_model_catalog(request: Request):
    env = read_env(get_env_path(request))
    catalogs = []
    for provider, entries in MODEL_CATALOG.items():
        models = [
            ModelOption(
                id=entry.id,
                label=entry.label,
                supports_reasoning=provider_capabilities(entry.id).supports_reasoning,
                supports_native_search=supports_native_search(entry.id),
            )
            for entry in entries
        ]
        catalogs.append(
            ProviderModelCatalog(
                provider=provider,
                label=PROVIDER_LABELS[provider],
                has_key=bool(env.get(_PROVIDER_KEY_ENV[provider])),
                models=models,
            )
        )
    return catalogs


@router.put("/config/models", response_model=ModelsConfigDoc)
def put_models(body: ModelsConfigDoc, request: Request):
    # Fields omitted from the request body still arrive with their class
    # default (Pydantic fills them in), so only fields the client actually
    # sent are written — otherwise an omitted field would silently overwrite
    # a previously-configured value with the schema default.
    provided = body.model_dump(exclude_unset=True)
    updates = {_MODEL_ENV[f]: v for f, v in provided.items()}
    fresh = write_env_updates(updates, get_env_path(request))
    refresh_app_settings(request.app, fresh)
    return get_models(request)
