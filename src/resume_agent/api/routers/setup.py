"""GET /setup/status — one aggregate the gate, wizard, and dashboard all read."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from resume_agent.api.schemas.secrets import LLM_KEY_ENV_VARS
from resume_agent.api.schemas.setup import (
    ProfileStatus,
    SearchStatus,
    SecretsStatus,
    SetupStatusOut,
    SourcesStatus,
)
from resume_agent.services.env_config import read_env
from resume_agent.services.sources import list_sources

router = APIRouter()


@router.get("/setup/status", response_model=SetupStatusOut)
def get_setup_status(request: Request):
    env = read_env(request.app.state.env_path)
    secrets = SecretsStatus(
        anthropic_key=bool(env.get("ANTHROPIC_API_KEY")),
        any_llm_key=any(env.get(k) for k in LLM_KEY_ENV_VARS),
    )

    docs = request.app.state.document_store.list()
    facts_path = request.app.state.data_dir / "profile" / "facts.json"
    facts_built_at = (
        datetime.fromtimestamp(facts_path.stat().st_mtime, tz=timezone.utc)
        .isoformat(timespec="seconds")
        if facts_path.exists() else None
    )
    profile_cfg = request.app.state.config_store.get("profile")
    profile = ProfileStatus(
        document_count=len(docs),
        has_resume=any(d.doc_type == "resume" for d in docs),
        facts_built_at=facts_built_at,
        github_username=profile_cfg.github_username,
    )

    search_cfg = request.app.state.config_store.get("search")
    search = SearchStatus(
        configured=bool(search_cfg.keywords or search_cfg.titles or search_cfg.role_anchors)
    )

    try:
        enabled = sum(
            1
            for v in list_sources(
                connectors_path=str(request.app.state.config_store.config_dir / "connectors.yaml"),
                settings=request.app.state.settings,
            )
            if v.enabled
        )
    except Exception:  # missing/broken connectors.yaml must not 500 the gate
        enabled = 0
    sources = SourcesStatus(enabled_count=enabled)

    complete = (
        secrets.any_llm_key and profile.has_resume
        and profile.facts_built_at is not None
        and search.configured and sources.enabled_count > 0
    )
    return SetupStatusOut(secrets=secrets, profile=profile, search=search,
                          sources=sources, complete=complete)
