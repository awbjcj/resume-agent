import pytest

from datetime import datetime, timedelta, timezone
from pathlib import Path

from resume_agent.progress import (
    ProgressReporter,
    atomic_write_text,
    clear_progress,
    is_displayable,
    progress_stats,
    read_all,
    read_progress,
)
from resume_agent.security.paths import PathEscapeError


def test_read_progress_missing_returns_none(tmp_path):
    assert read_progress("pull", tmp_path) is None
    assert read_all(tmp_path) == {}


def test_atomic_write_retries_transient_windows_replace_error(monkeypatch, tmp_path):
    target = tmp_path / "run.json"
    real_replace = __import__("os").replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr("resume_agent.progress.os.replace", flaky_replace)
    monkeypatch.setattr("resume_agent.progress.time.sleep", lambda _seconds: None)

    atomic_write_text(target, '{"state": "done"}', root=tmp_path)

    assert target.read_text(encoding="utf-8") == '{"state": "done"}'
    assert calls["n"] == 2


def test_atomic_write_rejects_a_path_outside_its_owning_root(tmp_path):
    outside = tmp_path / "outside.json"

    with pytest.raises(PathEscapeError):
        atomic_write_text(outside, '{"unsafe": true}', root=tmp_path / "progress")
    assert not outside.exists()


def test_read_progress_retries_transient_oserror(monkeypatch, tmp_path):
    """A live record momentarily unreadable (Windows ``os.replace``/``open``
    sharing violation) must NOT read as None — that turns into a spurious 404 on
    the SSE/GET run-lookup gates. read_progress retries the transient OSError and
    still returns the existing record."""
    ProgressReporter("pull", tmp_path).done()  # a real, present record

    real_read_text = Path.read_text
    calls = {"n": 0}

    def flaky_read_text(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "The process cannot access the file")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    rec = read_progress("pull", tmp_path)
    assert rec is not None and rec["state"] == "done"
    assert calls["n"] >= 2  # proved it retried past the transient failure


def test_read_progress_persistent_oserror_returns_none(monkeypatch, tmp_path):
    """An unreadable-forever file exhausts the retries and falls back to None."""
    ProgressReporter("pull", tmp_path).done()

    def always_raises(self, *args, **kwargs):
        raise PermissionError(13, "locked")

    monkeypatch.setattr(Path, "read_text", always_raises)
    assert read_progress("pull", tmp_path) is None


def test_read_progress_corrupt_json_returns_none_without_retry(monkeypatch, tmp_path):
    """Corrupt content is terminal, not transient — return None immediately so a
    poll loop never spins on a permanently-broken file."""
    (tmp_path / "pull.json").write_text("{ not json", encoding="utf-8")

    sleeps = {"n": 0}
    monkeypatch.setattr(
        "resume_agent.progress.time.sleep",
        lambda _s: sleeps.__setitem__("n", sleeps["n"] + 1),
    )

    assert read_progress("pull", tmp_path) is None
    assert sleeps["n"] == 0  # JSONDecodeError did not trigger a retry/backoff


def test_reporter_begin_step_done_roundtrips(tmp_path):
    rep = ProgressReporter("discover", tmp_path)
    rep.begin(total=3, label="Scoring fit", phase_index=3, phase_count=3)
    rep.step(3)  # final step always writes despite throttle
    rec = read_progress("discover", tmp_path)
    assert rec is not None
    assert rec["state"] == "running"
    assert rec["current"] == 3 and rec["total"] == 3
    assert rec["phase_index"] == 3 and rec["phase_count"] == 3

    rep.done()
    rec = read_progress("discover", tmp_path)
    assert rec is not None
    assert rec["state"] == "done"
    assert rec["error"] is None


def test_reporter_done_with_error_records_error_state(tmp_path):
    rep = ProgressReporter("tailor", tmp_path)
    rep.begin(total=1, label="Starting")
    rep.done(error="boom")
    rec = read_progress("tailor", tmp_path)
    assert rec is not None
    assert rec["state"] == "error" and rec["error"] == "boom"


def test_reporter_done_without_begin_still_emits_terminal(tmp_path):
    rep = ProgressReporter("pull", tmp_path)
    rep.done()
    rec = read_progress("pull", tmp_path)
    assert rec is not None and rec["state"] == "done"


def test_reporter_step_before_begin_is_noop(tmp_path):
    rep = ProgressReporter("pull", tmp_path)
    rep.step(5)  # no begin() yet
    assert read_progress("pull", tmp_path) is None


def test_reporter_extra_fields_persist(tmp_path):
    rep = ProgressReporter("pull", tmp_path)
    rep.begin(total=2, label="Starting", added=0)
    rep.step(2, added=7)
    rec = read_progress("pull", tmp_path)
    assert rec is not None
    assert rec["added"] == 7


def test_clear_progress_removes_file(tmp_path):
    rep = ProgressReporter("pull", tmp_path)
    rep.done()
    assert read_progress("pull", tmp_path) is not None
    clear_progress("pull", tmp_path)
    assert read_progress("pull", tmp_path) is None


def test_progress_paths_reject_traversal_without_touching_a_neighbor(tmp_path):
    root = tmp_path / "progress"
    outside = tmp_path / "outside.json"
    outside.write_text('{"keep": true}', encoding="utf-8")

    assert read_progress("../outside", root) is None
    clear_progress("../outside", root)
    assert outside.read_text(encoding="utf-8") == '{"keep": true}'
    with pytest.raises(PathEscapeError):
        ProgressReporter("../outside", root)


def test_progress_stats_computes_percentage_and_eta():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # 10s elapsed for 10/40 done → 1s/item → 30 remaining → ~30s ETA.
    record = {
        "process": "discover",
        "state": "running",
        "label": "Scoring fit",
        "phase_index": 3,
        "phase_count": 3,
        "current": 10,
        "total": 40,
        "started_at": start.isoformat(),
        "updated_at": (start + timedelta(seconds=10)).isoformat(),
    }
    stats = progress_stats(record)
    assert stats.pct == 25
    assert stats.phase == "Phase 3 of 3"
    assert stats.eta_text == "30s"


def test_progress_stats_done_is_full_and_no_eta():
    stats = progress_stats(
        {"process": "tailor", "state": "done", "current": 4, "total": 4}
    )
    assert stats.pct == 100
    assert stats.eta_text is None


def test_progress_stats_zero_total_does_not_divide():
    stats = progress_stats(
        {"process": "pull", "state": "running", "current": 0, "total": 0}
    )
    assert stats.pct == 0
    assert stats.eta_text is None


def test_is_displayable_running_always_and_terminal_within_ttl():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert is_displayable({"state": "running"}, now=now) is True

    fresh = {"state": "done", "updated_at": (now - timedelta(seconds=5)).isoformat()}
    assert is_displayable(fresh, now=now) is True

    stale = {"state": "done", "updated_at": (now - timedelta(seconds=120)).isoformat()}
    assert is_displayable(stale, now=now) is False
