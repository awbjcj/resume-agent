"""Prune endpoint: preview (dryRun) or run, with optional config overrides."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.schemas.jobs import PruneOverrides, PruneReportOut
from resume_agent.tracking.prune_config import load_prune_config
from resume_agent.tracking.repository import prune_preview, prune_run

router = APIRouter()
_PRUNE_CONFIG_PATH = "config/prune.yaml"


@router.post("/prune", response_model=PruneReportOut)
def prune(body: PruneOverrides, session: Session = Depends(get_session)):
    config = load_prune_config(_PRUNE_CONFIG_PATH)
    overrides = {
        k: v for k, v in (
            ("fit_threshold", body.fit_threshold),
            ("stale_days", body.stale_days),
            ("retention_days", body.retention_days),
        ) if v is not None
    }
    if overrides:
        config = config.model_copy(update=overrides)
    report = prune_preview(session, config) if body.dry_run else prune_run(session, config)
    return PruneReportOut.model_validate(report)
