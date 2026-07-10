"""Source Manager CRUD and preview routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.sources import (
    AddSourceIn,
    SourcePatchIn,
    SourceOut,
    SourcePreviewIn,
    SourcePreviewOut,
)
from resume_agent.config import Settings
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


@router.get("/sources", response_model=list[SourceOut])
def list_sources_route(settings: Settings = Depends(get_settings_dep)):
    return [SourceOut.model_validate(view) for view in list_sources(settings=settings)]


@router.post("/sources/preview", response_model=SourcePreviewOut)
def preview_source_route(body: SourcePreviewIn):
    return SourcePreviewOut.model_validate(preview_source(body.url, label=body.label))


@router.post("/sources", response_model=SourceOut, status_code=201)
def add_source_route(body: AddSourceIn):
    return SourceOut.model_validate(_guard(lambda: add_source(body.url, label=body.label)))


@router.patch("/sources/{source_id}", response_model=SourceOut)
def patch_source_route(source_id: str, body: SourcePatchIn):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiException(400, "VALIDATION_ERROR", "Provide enabled and/or limit.")
    return SourceOut.model_validate(
        _guard(lambda: patch_source(source_id, **changes))
    )


@router.delete("/sources/{source_id}", status_code=204)
def remove_source_route(source_id: str):
    _guard(lambda: remove_source(source_id))
