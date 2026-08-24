"""Admin-controlled provider routing backed by the deployment .env file."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from resume_agent.api.deps import refresh_platform_settings, require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_routing import (
    ProviderRoutingStatus,
    RoutingConfigDoc,
    RoutingKeyStatus,
    RoutingUpdate,
)
from resume_agent.llm_routing import (
    ROUTE_MODE_FIELDS,
    SUB2API_KEY_FIELDS,
    RouteConfigError,
    effective_mode,
)
from resume_agent.llm_runner import PROVIDER_LABELS
from resume_agent.services.env_config import write_env_updates
from resume_agent.tenancy.context import UserContext

router = APIRouter(prefix="/admin/routing", tags=["admin"])

_BODY_TO_SETTING = {
    "base_url": "sub2api_base_url",
    **{f"{provider}_key": field for provider, field in SUB2API_KEY_FIELDS.items()},
    **{field: field for field in ROUTE_MODE_FIELDS.values()},
}
_UPDATE_FIELDS = {body: setting.upper() for body, setting in _BODY_TO_SETTING.items()}


def _key_status(value: str) -> RoutingKeyStatus:
    return RoutingKeyStatus(
        is_set=bool(value), hint=value[-4:] if len(value) >= 8 else None
    )


def _document(settings) -> RoutingConfigDoc:
    providers: list[ProviderRoutingStatus] = []
    for provider, key_field in SUB2API_KEY_FIELDS.items():
        error = None
        resolved = None
        try:
            resolved = effective_mode(provider, settings)
        except RouteConfigError as exc:
            error = str(exc)
        providers.append(
            ProviderRoutingStatus(
                provider=provider,
                label=PROVIDER_LABELS[provider],
                route_mode=getattr(settings, ROUTE_MODE_FIELDS[provider]),
                effective_mode=resolved,
                configuration_error=error,
                key=_key_status(getattr(settings, key_field)),
            )
        )
    return RoutingConfigDoc(
        base_url=settings.sub2api_base_url,
        providers=providers,
    )


@router.get("")
def get_routing(
    request: Request, _context: UserContext = Depends(require_admin)
) -> RoutingConfigDoc:
    return _document(request.app.state.settings)


@router.put("")
def put_routing(
    body: RoutingUpdate,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> RoutingConfigDoc:
    provided = body.model_dump(exclude_unset=True)
    candidate = request.app.state.settings.model_copy(
        update={
            _BODY_TO_SETTING[field]: value or "" for field, value in provided.items()
        }
    )
    errors: list[str] = []
    for provider in SUB2API_KEY_FIELDS:
        try:
            effective_mode(provider, candidate)
        except RouteConfigError as exc:
            errors.append(str(exc))
    if errors:
        raise ApiException(422, "INVALID_ROUTING_CONFIG", "; ".join(errors))
    updates = {_UPDATE_FIELDS[field]: (value or "") for field, value in provided.items()}
    fresh = write_env_updates(updates, request.app.state.env_path)
    refresh_platform_settings(request.app, fresh)
    return _document(fresh)
