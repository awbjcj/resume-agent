"""Source Manager CRUD and preview routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from resume_agent.api.deps import (
    get_config_store,
    get_profile_dir,
    get_run_manager,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.sources import (
    AddSourceIn,
    DiscoverSourcesIn,
    SourcePatchIn,
    SourceOut,
    SourcePreviewIn,
    SourcePreviewOut,
)
from resume_agent.api.runs.launch import launch
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.runs import RunOut
from resume_agent.config import Settings
from resume_agent.llm_runner import plan_search, resolve_api_key
from resume_agent.services.source_discovery import run_source_discovery
from resume_agent.services.sources import (
    SourceError,
    add_source,
    list_sources,
    preview_source,
    patch_source,
    remove_source,
)

router = APIRouter()


def _guard(call):
    try:
        return call()
    except SourceError as exc:
        raise ApiException(400, "SOURCE_ERROR", str(exc)) from exc


def _config_paths(request: Request) -> tuple[str, str]:
    config_dir = get_config_store(request).config_dir
    return str(config_dir / "connectors.yaml"), str(config_dir / "search.yaml")


@router.get("/sources", response_model=list[SourceOut])
def list_sources_route(
    request: Request, settings: Settings = Depends(get_settings_dep)
):
    connectors_path, _ = _config_paths(request)
    return [
        SourceOut.model_validate(view)
        for view in list_sources(connectors_path=connectors_path, settings=settings)
    ]


@router.post("/sources/preview", response_model=SourcePreviewOut)
def preview_source_route(request: Request, body: SourcePreviewIn):
    _, search_path = _config_paths(request)
    return SourcePreviewOut.model_validate(
        preview_source(**body.model_dump(), search_path=search_path)
    )


@router.post("/sources", response_model=SourceOut, status_code=201)
def add_source_route(request: Request, body: AddSourceIn):
    connectors_path, search_path = _config_paths(request)
    return SourceOut.model_validate(
        _guard(
            lambda: add_source(
                **body.model_dump(),
                connectors_path=connectors_path,
                search_path=search_path,
            )
        )
    )


@router.post("/sources/discover", response_model=RunOut, status_code=202)
def discover_sources_route(
    body: DiscoverSourcesIn,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    required_models = tuple(dict.fromkeys((settings.mid_model, settings.cheap_model)))
    missing = [model for model in required_models if not resolve_api_key(model)]
    if missing:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            f"Missing API key for configured model(s): {', '.join(missing)}",
        )
    try:
        search_plan = plan_search(settings.mid_model, settings.search_mode)
    except ValueError as exc:
        raise ApiException(400, "SEARCH_DISABLED", str(exc)) from exc
    if search_plan.strategy == "none":
        raise ApiException(
            400,
            "SEARCH_DISABLED",
            "Source Scout needs web search; change search_mode from off.",
        )

    connectors_path, search_path = _config_paths(request)
    profile_dir = get_profile_dir(request)

    def work(reporter):
        return run_source_discovery(
            reporter,
            prompt=body.prompt,
            connectors_path=connectors_path,
            search_path=search_path,
            profile_dir=profile_dir,
            browser_enabled=settings.browser_enabled,
        )

    return launch(mgr, "source-discovery", work, singleton_key="source-discovery")


@router.patch("/sources/{source_id}", response_model=SourceOut)
def patch_source_route(request: Request, source_id: str, body: SourcePatchIn):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiException(400, "VALIDATION_ERROR", "Provide enabled and/or limit.")
    connectors_path, _ = _config_paths(request)
    return SourceOut.model_validate(
        _guard(
            lambda: patch_source(source_id, connectors_path=connectors_path, **changes)
        )
    )


@router.delete("/sources/{source_id}", status_code=204)
def remove_source_route(request: Request, source_id: str):
    connectors_path, _ = _config_paths(request)
    _guard(lambda: remove_source(source_id, connectors_path=connectors_path))
