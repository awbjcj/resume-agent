"""Typed per-domain config resources. Storage lives behind ConfigStore."""

from __future__ import annotations

from fastapi import APIRouter, Request

from resume_agent.api.schemas.config import (
    ProfileConfigDoc,
    PruneConfigDoc,
    RenderConfigDoc,
    ReviewConfigDoc,
    SearchConfigDoc,
    StyleGuideDoc,
)
from resume_agent.api.deps import get_config_store
from resume_agent.api.errors import ApiException
from resume_agent.render.templates import TemplateNotFoundError, resolve_template
from resume_agent.services.config_store import ConfigStore

router = APIRouter()


def _store(request: Request) -> ConfigStore:
    return get_config_store(request)


@router.get("/config/search", response_model=SearchConfigDoc)
def get_search(request: Request):
    return _store(request).get("search")


@router.put("/config/search", response_model=SearchConfigDoc)
def put_search(body: SearchConfigDoc, request: Request):
    return _store(request).put("search", body)


@router.get("/config/review", response_model=ReviewConfigDoc)
def get_review(request: Request):
    return _store(request).get("review")


@router.put("/config/review", response_model=ReviewConfigDoc)
def put_review(body: ReviewConfigDoc, request: Request):
    return _store(request).put("review", body)


@router.get("/config/prune", response_model=PruneConfigDoc)
def get_prune(request: Request):
    return _store(request).get("prune")


@router.put("/config/prune", response_model=PruneConfigDoc)
def put_prune(body: PruneConfigDoc, request: Request):
    return _store(request).put("prune", body)


@router.get("/config/render", response_model=RenderConfigDoc)
def get_render(request: Request):
    return _store(request).get("render")


@router.put("/config/render", response_model=RenderConfigDoc)
def put_render(body: RenderConfigDoc, request: Request):
    try:
        resolve_template(body.template)
    except TemplateNotFoundError as exc:
        raise ApiException(422, "template_not_found", str(exc)) from exc
    return _store(request).put("render", body)


@router.get("/config/style-guide", response_model=StyleGuideDoc)
def get_style_guide(request: Request):
    return _store(request).get("style_guide")


@router.put("/config/style-guide", response_model=StyleGuideDoc)
def put_style_guide(body: StyleGuideDoc, request: Request):
    return _store(request).put("style_guide", body)


@router.get("/config/profile", response_model=ProfileConfigDoc)
def get_profile_config(request: Request):
    return _store(request).get("profile")


@router.put("/config/profile", response_model=ProfileConfigDoc)
def put_profile_config(body: ProfileConfigDoc, request: Request):
    return _store(request).put("profile", body)
