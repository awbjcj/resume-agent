"""Prune endpoint: preview (dryRun) or run, with optional config overrides."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.schemas.jobs import PruneOverrides, PruneReportOut
from resume_tailor_harness.services.prune import prune as prune_jobs

router = APIRouter()


@router.post("/prune", response_model=PruneReportOut)
def prune(body: PruneOverrides, session: Session = Depends(get_session)):
    report = prune_jobs(
        session,
        dry_run=body.dry_run,
        fit_threshold=body.fit_threshold,
        stale_days=body.stale_days,
        retention_days=body.retention_days,
    )
    return PruneReportOut.model_validate(report)
