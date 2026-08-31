"""Prune use-case: load config, apply sparse overrides, dispatch preview/run."""

from __future__ import annotations

from sqlmodel import Session

from resume_tailor_harness.tracking.prune import PruneReport
from resume_tailor_harness.tracking.prune_config import load_prune_config
from resume_tailor_harness.tracking.repository import prune_preview, prune_run

DEFAULT_PRUNE_CONFIG = "config/prune.yaml"


def prune(
    session: Session,
    *,
    dry_run: bool,
    fit_threshold: int | None = None,
    stale_days: int | None = None,
    retention_days: int | None = None,
    config_path: str = DEFAULT_PRUNE_CONFIG,
) -> PruneReport:
    """Archive junk / expire old jobs. ``dry_run`` counts without writing."""
    cfg = load_prune_config(config_path)
    overrides = {
        k: v
        for k, v in (
            ("fit_threshold", fit_threshold),
            ("stale_days", stale_days),
            ("retention_days", retention_days),
        )
        if v is not None
    }
    if overrides:
        cfg = cfg.model_copy(update=overrides)
    return prune_preview(session, cfg) if dry_run else prune_run(session, cfg)
