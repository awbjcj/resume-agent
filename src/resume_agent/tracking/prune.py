from dataclasses import dataclass
from datetime import datetime, timezone

from resume_agent.tracking.prune_config import PruneConfig
from resume_agent.tracking.tables import JobStatus


@dataclass
class PruneRow:
    job_id: int
    status: str
    fit_score: int | None
    posted_at: datetime | None
    created_at: datetime
    archived_at: datetime | None
    has_progress: bool


@dataclass(frozen=True)
class PruneReport:
    archived: int
    expired: int
    skipped: int
    rejected: int = 0
    low_fit: int = 0
    stale: int = 0


def is_zero_progress(row: PruneRow) -> bool:
    """Data-level mirror of repository.has_progress for pure prune predicates."""
    return not row.has_progress


def _age_days(dt: datetime, now: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return (now - dt).total_seconds() / 86400.0


def prune_reason(row: PruneRow, config: PruneConfig, now: datetime) -> str | None:
    """Primary archive reason, ordered so preview counts never double-count."""
    if config.enable_rejected and row.status == JobStatus.rejected.value:
        return "rejected"
    if config.enable_low_fit and row.fit_score is not None and row.fit_score < config.fit_threshold:
        return "low_fit"
    if config.enable_stale:
        ref = row.posted_at or row.created_at
        if _age_days(ref, now) > config.stale_days:
            return "stale"
    return None


def _matches(row: PruneRow, config: PruneConfig, now: datetime) -> bool:
    return prune_reason(row, config, now) is not None


def prune_candidates(rows: list[PruneRow], config: PruneConfig, now: datetime) -> list[PruneRow]:
    """Zero-progress, not-yet-archived rows matching any enabled rule."""
    return [
        r for r in rows
        if r.archived_at is None and is_zero_progress(r) and _matches(r, config, now)
    ]


def prune_skipped(rows: list[PruneRow], config: PruneConfig, now: datetime) -> list[PruneRow]:
    """Rows that match a rule but are kept because they have user progress."""
    return [
        r for r in rows
        if r.archived_at is None and r.has_progress and _matches(r, config, now)
    ]


def expire_candidates(rows: list[PruneRow], config: PruneConfig, now: datetime) -> list[PruneRow]:
    """Archived, zero-progress rows older than the retention window."""
    return [
        r for r in rows
        if r.archived_at is not None
        and is_zero_progress(r)
        and _age_days(r.archived_at, now) > config.retention_days
    ]


def prune_reason_counts(
    rows: list[PruneRow], config: PruneConfig, now: datetime
) -> dict[str, int]:
    """Primary archive-reason counts for zero-progress prune candidates."""
    counts = {"rejected": 0, "low_fit": 0, "stale": 0}
    for row in prune_candidates(rows, config, now):
        reason = prune_reason(row, config, now)
        if reason is not None:
            counts[reason] += 1
    return counts
