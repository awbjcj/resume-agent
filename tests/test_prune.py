from datetime import datetime, timedelta, timezone

from resume_agent.tracking.prune import (
    PruneRow,
    expire_candidates,
    is_zero_progress,
    prune_candidates,
    prune_reason_counts,
    prune_skipped,
)
from resume_agent.tracking.prune_config import PruneConfig
from resume_agent.tracking.tables import JobStatus

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _row(job_id=1, status=JobStatus.raw.value, fit=None, posted=None,
         created=NOW, archived=None, progress=False) -> PruneRow:
    return PruneRow(
        job_id=job_id, status=status, fit_score=fit, posted_at=posted,
        created_at=created, archived_at=archived, has_progress=progress,
    )


def test_prune_candidates_match_each_enabled_rule():
    cfg = PruneConfig()
    rejected = _row(job_id=1, status=JobStatus.rejected.value)
    low_fit = _row(job_id=2, fit=10)
    stale = _row(job_id=3, posted=NOW - timedelta(days=90))
    fresh_good = _row(job_id=4, fit=95, posted=NOW)

    ids = {r.job_id for r in prune_candidates([rejected, low_fit, stale, fresh_good], cfg, NOW)}
    assert ids == {1, 2, 3}


def test_is_zero_progress_is_inverse_of_progress_flag():
    assert is_zero_progress(_row(progress=False)) is True
    assert is_zero_progress(_row(progress=True)) is False


def test_prune_reason_counts_uses_primary_reason_without_double_counting():
    cfg = PruneConfig()
    rejected_low_fit = _row(job_id=1, status=JobStatus.rejected.value, fit=1)
    stale = _row(job_id=2, posted=NOW - timedelta(days=90))

    assert prune_reason_counts([rejected_low_fit, stale], cfg, NOW) == {
        "rejected": 1,
        "low_fit": 0,
        "stale": 1,
    }


def test_prune_skips_jobs_with_progress():
    cfg = PruneConfig()
    matched_but_progress = _row(job_id=5, status=JobStatus.rejected.value, progress=True)
    assert prune_candidates([matched_but_progress], cfg, NOW) == []
    assert {r.job_id for r in prune_skipped([matched_but_progress], cfg, NOW)} == {5}


def test_prune_ignores_already_archived():
    cfg = PruneConfig()
    archived = _row(job_id=6, fit=5, archived=NOW)
    assert prune_candidates([archived], cfg, NOW) == []


def test_disabled_rules_are_not_applied():
    cfg = PruneConfig(enable_low_fit=False, enable_stale=False)
    low_fit = _row(job_id=7, fit=1)
    rejected = _row(job_id=8, status=JobStatus.rejected.value)
    assert {r.job_id for r in prune_candidates([low_fit, rejected], cfg, NOW)} == {8}


def test_expire_candidates_only_old_archived_zero_progress():
    cfg = PruneConfig()
    old = _row(job_id=9, archived=NOW - timedelta(days=45))
    recent = _row(job_id=10, archived=NOW - timedelta(days=5))
    old_with_progress = _row(job_id=11, archived=NOW - timedelta(days=45), progress=True)
    never_archived = _row(job_id=12, archived=None)

    ids = {r.job_id for r in expire_candidates([old, recent, old_with_progress, never_archived], cfg, NOW)}
    assert ids == {9}
