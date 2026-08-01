"""GET /setup/status — one aggregate the gate, wizard, and dashboard all read."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Request

from resume_agent.api.schemas.config import ProfileConfigDoc, SearchConfigDoc
from resume_agent.api.schemas.setup import (
    ProfileStatus,
    SearchStatus,
    SecretsStatus,
    SetupStatusOut,
    SourcesStatus,
)
from resume_agent.llm_runner import MODEL_CATALOG, provider_access_available
from resume_agent.services.sources import list_sources
from resume_agent.api.deps import (
    get_config_store,
    get_document_store,
    get_profile_dir,
    get_settings_dep,
)

router = APIRouter()


@router.get("/setup/status", response_model=SetupStatusOut)
def get_setup_status(request: Request):
    settings = get_settings_dep(request)
    secrets = SecretsStatus(
        anthropic_key=provider_access_available("anthropic", settings=settings),
        any_llm_key=any(
            provider_access_available(provider, settings=settings)
            for provider in MODEL_CATALOG
        ),
    )

    document_store = get_document_store(request)
    config_store = get_config_store(request)
    docs = document_store.list()
    facts_path = get_profile_dir(request) / "facts.json"
    facts_built_at = (
        datetime.fromtimestamp(facts_path.stat().st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        if facts_path.exists()
        else None
    )
    profile_cfg = cast(ProfileConfigDoc, config_store.get("profile"))
    profile = ProfileStatus(
        document_count=len(docs),
        has_resume=any(d.doc_type == "resume" for d in docs),
        facts_built_at=facts_built_at,
        github_username=profile_cfg.github_username,
    )

    search_cfg = cast(SearchConfigDoc, config_store.get("search"))
    search = SearchStatus(
        configured=bool(
            search_cfg.keywords or search_cfg.titles or search_cfg.role_anchors
        )
    )

    try:
        enabled = sum(
            1
            for v in list_sources(
                connectors_path=str(config_store.config_dir / "connectors.yaml"),
                settings=settings,
            )
            if v.enabled
        )
    except Exception:  # missing/broken connectors.yaml must not 500 the gate
        enabled = 0
    sources = SourcesStatus(enabled_count=enabled)

    complete = (
        secrets.any_llm_key
        and profile.has_resume
        and profile.facts_built_at is not None
        and search.configured
        and sources.enabled_count > 0
    )
    return SetupStatusOut(
        secrets=secrets,
        profile=profile,
        search=search,
        sources=sources,
        complete=complete,
    )
