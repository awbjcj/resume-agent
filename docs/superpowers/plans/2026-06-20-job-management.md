# Job Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add archive (reversible), hard-delete (zero-progress only), and trash-bin auto-prune for jobs, surfaced through a new Triage page, an enhanced Pipeline board, and a `prune` CLI command.

**Architecture:** One orthogonal `Job.archived_at` flag makes hiding reversible and lossless; one `has_progress` predicate is the single gate every irreversible path passes through. Prune logic is pure functions over a `PruneRow` dataclass (mirroring `filtering.py`); a thin `prune_run` orchestrator in `repository.py` applies them. Dashboard surfaces call these primitives.

**Tech Stack:** Python, SQLModel/SQLAlchemy (SQLite), Typer CLI, Streamlit, pytest.

**Test command (offline, no API key):** `.venv/Scripts/python.exe -m pytest <path> -v`

---

## File Structure

| File                                        | Responsibility                                                                                                                                | Action |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| `src/resume_agent/tracking/tables.py`       | Add `Job.archived_at` column                                                                                                                  | Modify |
| `src/resume_agent/tracking/migrate.py`      | `ensure_archived_at_column`                                                                                                                   | Modify |
| `src/resume_agent/db.py`                    | Wire migration into `init_db`                                                                                                                 | Modify |
| `src/resume_agent/tracking/repository.py`   | `has_progress`, `archive_job`, `restore_job`, `delete_job`, `prune_preview`, `prune_run`; archived filter on `jobs_by_status`/`status_counts` | Modify |
| `src/resume_agent/tracking/queries.py`      | Archived filter on `shortlist_rows`/`pipeline_rows`; `triage_rows`, `archived_rows`, `TriageRow`                                              | Modify |
| `src/resume_agent/tracking/prune.py`        | Pure prune predicates, `PruneRow`, `PruneReport`                                                                                              | Create |
| `src/resume_agent/tracking/prune_config.py` | `PruneConfig`, `load_prune_config`                                                                                                            | Create |
| `config/prune.yaml.example`                 | Documented default thresholds                                                                                                                 | Create |
| `src/resume_agent/cli.py`                   | `prune` command                                                                                                                               | Modify |
| `src/resume_agent/dashboard/selection.py`   | Pure selection-state helpers                                                                                                                  | Create |
| `src/resume_agent/dashboard/pages.py`       | `render_triage_page`, prune panel, pipeline enhancements                                                                                      | Modify |
| `src/resume_agent/dashboard/app.py`         | Sidebar nav + routing for Triage                                                                                                              | Modify |

Tasks are ordered as a dependency chain; each leaves the suite green.

---

## Task 1: Add `archived_at` column + migration

**Files:**

- Modify: `src/resume_agent/tracking/tables.py`
- Modify: `src/resume_agent/tracking/migrate.py`
- Modify: `src/resume_agent/db.py`
- Test: `tests/test_migrate.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_migrate.py`:

```python
def test_ensure_archived_at_column_adds_missing_column():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    from resume_agent.tracking.migrate import ensure_archived_at_column
    ensure_archived_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        indexes = [row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))]
    assert "archived_at" in cols
    assert "ix_jobs_archived_at" in indexes


def test_ensure_archived_at_column_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    from resume_agent.tracking.migrate import ensure_archived_at_column
    ensure_archived_at_column(engine)
    ensure_archived_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
    assert cols.count("archived_at") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate.py -v`
Expected: FAIL with `ImportError: cannot import name 'ensure_archived_at_column'`

- [ ] **Step 3: Add the column to the model**

In `src/resume_agent/tracking/tables.py`, inside `class Job`, after the `posted_at` line:

```python
    archived_at: datetime | None = Field(default=None, index=True)
```

- [ ] **Step 4: Add the migration**

Append to `src/resume_agent/tracking/migrate.py`:

```python
def ensure_archived_at_column(engine: Engine) -> None:
    """Idempotently add the ``jobs.archived_at`` column (soft-archive timestamp)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "archived_at" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN archived_at DATETIME"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_archived_at ON jobs (archived_at)")
        )
```

- [ ] **Step 5: Wire it into `init_db`**

In `src/resume_agent/db.py`, update the import and `init_db`:

```python
from resume_agent.tracking.migrate import (
    ensure_archived_at_column,
    ensure_dedup_key_column,
    ensure_posted_at_column,
)
```

```python
def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_dedup_key_column(engine)
    ensure_posted_at_column(engine)
    ensure_archived_at_column(engine)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/tracking/tables.py src/resume_agent/tracking/migrate.py src/resume_agent/db.py tests/test_migrate.py
git commit -m "Add jobs.archived_at column and migration"
```

---

## Task 2: `has_progress` safety predicate

**Files:**

- Modify: `src/resume_agent/tracking/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repository.py`:

```python
def test_has_progress_true_for_advanced_status_and_children():
    from resume_agent.tracking.repository import (
        has_progress, save_application, save_resume_version,
    )
    from resume_agent.tracking.tables import Application, ResumeVersion

    with _session() as s:
        raw = save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        approved = save_job(s, Job(source="m", jd_text="b", status=JobStatus.approved.value))
        with_version = save_job(s, Job(source="m", jd_text="c", status=JobStatus.raw.value))
        save_resume_version(s, ResumeVersion(job_id=_require_id(with_version.id), round=1))
        with_app = save_job(s, Job(source="m", jd_text="d", status=JobStatus.raw.value))
        save_application(s, Application(job_id=_require_id(with_app.id)))

        assert has_progress(s, _require_id(raw.id)) is False
        assert has_progress(s, _require_id(approved.id)) is True
        assert has_progress(s, _require_id(with_version.id)) is True
        assert has_progress(s, _require_id(with_app.id)) is True
        assert has_progress(s, 9999) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_has_progress_true_for_advanced_status_and_children -v`
Expected: FAIL with `ImportError: cannot import name 'has_progress'`

- [ ] **Step 3: Implement the predicate**

In `src/resume_agent/tracking/repository.py`, update the tables import to include `CoverLetter`, `Job`, `JobStatus` (CoverLetter and Job/JobStatus may already be partially imported — ensure all are present):

```python
from resume_agent.tracking.tables import (
    Application,
    ApplicationStatus,
    CoverLetter,
    Job,
    JobStatus,
    ResumeVersion,
    utcnow,
)
```

Add:

```python
_PROGRESS_STATUSES = {
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
}


def has_progress(session: Session, job_id: int) -> bool:
    """True if a job has user investment that must never be destroyed."""
    job = session.get(Job, job_id)
    if job is None:
        return False
    if job.status in _PROGRESS_STATUSES:
        return True
    for model in (Application, ResumeVersion, CoverLetter):
        if session.exec(select(model).where(model.job_id == job_id)).first() is not None:
            return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_has_progress_true_for_advanced_status_and_children -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/repository.py tests/test_repository.py
git commit -m "Add has_progress safety predicate"
```

---

## Task 3: `archive_job` / `restore_job`

**Files:**

- Modify: `src/resume_agent/tracking/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repository.py`:

```python
def test_archive_and_restore_preserve_status():
    from resume_agent.tracking.repository import archive_job, restore_job

    with _session() as s:
        job = save_job(s, Job(source="m", jd_text="a", status=JobStatus.shortlisted.value))
        jid = _require_id(job.id)

        archived = archive_job(s, jid)
        assert archived is not None
        assert archived.archived_at is not None
        assert archived.status == JobStatus.shortlisted.value

        restored = restore_job(s, jid)
        assert restored is not None
        assert restored.archived_at is None
        assert restored.status == JobStatus.shortlisted.value

        assert archive_job(s, 9999) is None
        assert restore_job(s, 9999) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_archive_and_restore_preserve_status -v`
Expected: FAIL with `ImportError: cannot import name 'archive_job'`

- [ ] **Step 3: Implement**

Add to `src/resume_agent/tracking/repository.py`:

```python
def archive_job(session: Session, job_id: int) -> Job | None:
    """Soft-archive a job (reversible). Status is left untouched."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    job.archived_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def restore_job(session: Session, job_id: int) -> Job | None:
    """Un-archive a job, restoring it to its exact prior stage."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    job.archived_at = None
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_archive_and_restore_preserve_status -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/repository.py tests/test_repository.py
git commit -m "Add archive_job and restore_job"
```

---

## Task 4: `delete_job` with cascade + progress guard

**Files:**

- Modify: `src/resume_agent/tracking/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repository.py`:

```python
def test_delete_job_cascades_children_and_refuses_progress():
    from resume_agent.tracking.repository import (
        delete_job, get_job, save_application, save_cover_letter, save_resume_version,
    )
    from resume_agent.tracking.tables import Application, CoverLetter, ResumeVersion
    from sqlmodel import select

    with _session() as s:
        junk = save_job(s, Job(source="m", jd_text="a", status=JobStatus.rejected.value))
        jid = _require_id(junk.id)
        assert delete_job(s, jid) is True
        assert get_job(s, jid) is None

        # A job with children/progress is refused and left intact.
        kept = save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        kid = _require_id(kept.id)
        save_resume_version(s, ResumeVersion(job_id=kid, round=1))
        save_application(s, Application(job_id=kid))
        save_cover_letter(s, CoverLetter(job_id=kid))
        assert delete_job(s, kid) is False
        assert get_job(s, kid) is not None
        assert s.exec(select(ResumeVersion).where(ResumeVersion.job_id == kid)).first() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_delete_job_cascades_children_and_refuses_progress -v`
Expected: FAIL with `ImportError: cannot import name 'delete_job'`

- [ ] **Step 3: Implement**

Add to `src/resume_agent/tracking/repository.py`:

```python
def delete_job(session: Session, job_id: int) -> bool:
    """Hard-delete a zero-progress job and its children in one transaction.

    Returns False (and changes nothing) if the job has user progress or is
    already gone. The progress check is the single irreversible-path guard.
    """
    if has_progress(session, job_id):
        return False
    job = session.get(Job, job_id)
    if job is None:
        return False
    # Dependency order: CoverLetter/Application can reference ResumeVersion.
    for model in (CoverLetter, Application, ResumeVersion):
        for child in session.exec(select(model).where(model.job_id == job_id)).all():
            session.delete(child)
    session.delete(job)
    session.commit()
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_delete_job_cascades_children_and_refuses_progress -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/repository.py tests/test_repository.py
git commit -m "Add delete_job with cascade and progress guard"
```

---

## Task 5: Exclude archived jobs from all views

**Files:**

- Modify: `src/resume_agent/tracking/repository.py` (`jobs_by_status`, `status_counts`)
- Modify: `src/resume_agent/tracking/queries.py` (`shortlist_rows`, `pipeline_rows`, `application_job_pairs`)
- Modify: `src/resume_agent/tracking/match_gap.py` (`_target_jobs`)
- Modify: `src/resume_agent/tracking/analytics.py` (`_rows`)
- Test: `tests/test_repository.py`, `tests/test_tracking_queries.py`, `tests/test_tracking_match_gap.py`, `tests/test_tracking_analytics.py`

> Note: `jobs_by_status` is also how the discovery pipeline (`discovery/pipeline.py`)
> reads jobs to process, so this one filter additionally stops archived jobs from
> being re-extracted/re-surfaced — a deliberate, beneficial side effect.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_repository.py`:

```python
def test_archived_jobs_excluded_from_status_views():
    from resume_agent.tracking.repository import archive_job, jobs_by_status, status_counts

    with _session() as s:
        a = save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        archive_job(s, _require_id(a.id))

        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1
        assert status_counts(s).get(JobStatus.raw.value) == 1
```

Add to `tests/test_tracking_queries.py`:

```python
def test_archived_jobs_excluded_from_shortlist_and_pipeline():
    from resume_agent.tracking.repository import archive_job

    with _session() as s:
        keep = save_job(s, Job(source="m", jd_text="a", company="Keep", title="E",
                               status=JobStatus.shortlisted.value, fit_score=70))
        hide = save_job(s, Job(source="m", jd_text="b", company="Hide", title="E",
                               status=JobStatus.shortlisted.value, fit_score=90))
        archive_job(s, _require_id(hide.id))

        assert [r.company for r in shortlist_rows(s)] == ["Keep"]
        assert [r.company for r in pipeline_rows(s)] == ["Keep"]
        _ = keep


def test_archived_jobs_excluded_from_application_job_pairs():
    from resume_agent.tracking.queries import application_job_pairs
    from resume_agent.tracking.repository import archive_job, save_application
    from resume_agent.tracking.tables import Application, ApplicationStatus

    with _session() as s:
        keep = save_job(s, Job(source="m", jd_text="a", company="Keep", title="E",
                               status=JobStatus.rendered.value))
        hide = save_job(s, Job(source="m", jd_text="b", company="Hide", title="E",
                               status=JobStatus.rendered.value))
        save_application(s, Application(job_id=_require_id(keep.id),
                                        status=ApplicationStatus.submitted.value))
        save_application(s, Application(job_id=_require_id(hide.id),
                                        status=ApplicationStatus.submitted.value))
        archive_job(s, _require_id(hide.id))

        assert [job.company for _, job in application_job_pairs(s)] == ["Keep"]
```

Add to `tests/test_tracking_match_gap.py`:

```python
def test_match_gap_excludes_archived_targets():
    from resume_agent.tracking.repository import archive_job

    facts = _facts({"lang": [Skill(name="Python")]})
    with _session() as s:
        _job(s, JobStatus.shortlisted.value, ["Python", "Go"])
        hidden = _job(s, JobStatus.shortlisted.value, ["Rust"])
        assert hidden.id is not None
        archive_job(s, hidden.id)
        report = match_gap(s, facts)
        assert report.target_total == 1
```

Add to `tests/test_tracking_analytics.py`:

```python
def test_analytics_excludes_archived_jobs():
    from resume_agent.tracking.repository import archive_job

    with _session() as session:
        _seed(session, "greenhouse", 85, ApplicationStatus.submitted.value)
        hidden = save_job(session, Job(source="adzuna", company="C", title="T",
                                       fit_score=90, status="rendered"))
        assert hidden.id is not None
        save_application(session, Application(job_id=hidden.id,
                                             status=ApplicationStatus.interview.value))
        archive_job(session, hidden.id)

        assert [stat.label for stat in source_stats(session)] == ["greenhouse"]
        bands = {stat.label: stat for stat in fit_band_stats(session)}
        assert bands["80-100"].applications == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py::test_archived_jobs_excluded_from_status_views tests/test_tracking_queries.py::test_archived_jobs_excluded_from_shortlist_and_pipeline tests/test_tracking_queries.py::test_archived_jobs_excluded_from_application_job_pairs tests/test_tracking_match_gap.py::test_match_gap_excludes_archived_targets tests/test_tracking_analytics.py::test_analytics_excludes_archived_jobs -v`
Expected: FAIL (archived rows still returned)

- [ ] **Step 3: Add the filter to `repository.py`**

In `src/resume_agent/tracking/repository.py`, replace `jobs_by_status` and `status_counts`:

```python
def jobs_by_status(session: Session, status: str) -> list[Job]:
    archived_col = cast(Any, Job.archived_at)
    return list(
        session.exec(
            select(Job).where(Job.status == status, archived_col.is_(None))
        ).all()
    )


def status_counts(session: Session) -> dict[str, int]:
    archived_col = cast(Any, Job.archived_at)
    rows = session.exec(
        select(Job.status, func.count())
        .where(archived_col.is_(None))
        .group_by(Job.status)
    ).all()
    return {status: count for status, count in rows}
```

`cast` and `Any` are already imported at the top of `repository.py`.

- [ ] **Step 4: Add the filter to `queries.py`**

In `src/resume_agent/tracking/queries.py`, in `shortlist_rows`, change the select to add the archived guard:

```python
    fit_score_col = cast(Any, Job.fit_score)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value, archived_col.is_(None))
        .order_by(fit_score_col.desc().nullslast())
    ).all()
```

In `pipeline_rows`, change the select:

```python
    status_col = cast(Any, Job.status)
    company_col = cast(Any, Job.company)
    title_col = cast(Any, Job.title)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .where(archived_col.is_(None))
        .order_by(status_col, company_col, title_col)
    ).all()
```

- [ ] **Step 5: Add the filter to `application_job_pairs`**

In `src/resume_agent/tracking/queries.py`, change `application_job_pairs` so Gmail
status sync also ignores archived jobs:

```python
def application_job_pairs(session: Session) -> list[tuple[Application, Job]]:
    """Every active application paired with its unarchived job."""
    archived_col = cast(Any, Job.archived_at)
    statement = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)  # type: ignore[arg-type]
        .where(archived_col.is_(None))
    )
    return [(app, job) for app, job in session.exec(statement).all()]
```

- [ ] **Step 6: Add the filter to `match_gap.py`**

In `src/resume_agent/tracking/match_gap.py`, replace `_target_jobs` so the Match-gap report ignores archived jobs (`cast` and `Any` are already imported there):

```python
def _target_jobs(session: Session) -> list[Job]:
    status_col = cast(Any, Job.status)
    id_col = cast(Any, Job.id)
    archived_col = cast(Any, Job.archived_at)
    return list(
        session.exec(
            select(Job)
            .where(status_col.in_(TARGET_STATUSES), archived_col.is_(None))
            .order_by(id_col)
        ).all()
    )
```

- [ ] **Step 7: Add the filter to `analytics.py`**

In `src/resume_agent/tracking/analytics.py`, add `Any` and `cast` to the typing
imports, then update `_rows`:

```python
from typing import Any, Callable, cast
```

```python
def _rows(session: Session) -> list[tuple[str, int | None, str]]:
    archived_col = cast(Any, Job.archived_at)
    statement = (
        select(Application.status, Job.fit_score, Job.source)
        .join(Job, Application.job_id == Job.id)  # type: ignore[arg-type]
        .where(Application.status != ApplicationStatus.ready.value, archived_col.is_(None))
    )
    return list(session.exec(statement).all())
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repository.py tests/test_tracking_queries.py tests/test_tracking_match_gap.py tests/test_tracking_analytics.py -v`
Expected: PASS (all, including existing tests)

- [ ] **Step 9: Commit**

```bash
git add src/resume_agent/tracking/repository.py src/resume_agent/tracking/queries.py src/resume_agent/tracking/match_gap.py src/resume_agent/tracking/analytics.py tests/test_repository.py tests/test_tracking_queries.py tests/test_tracking_match_gap.py tests/test_tracking_analytics.py
git commit -m "Exclude archived jobs from normal dashboard and sync views"
```

---

## Task 6: `PruneConfig` + loader + example file

**Files:**

- Create: `src/resume_agent/tracking/prune_config.py`
- Create: `config/prune.yaml.example`
- Test: `tests/test_prune_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prune_config.py`:

```python
from resume_agent.tracking.prune_config import PruneConfig, load_prune_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_prune_config(tmp_path / "nope.yaml")
    assert cfg.fit_threshold == 40
    assert cfg.stale_days == 60
    assert cfg.retention_days == 30
    assert cfg.enable_rejected is True
    assert cfg.enable_low_fit is True
    assert cfg.enable_stale is True


def test_loads_overrides_from_yaml(tmp_path):
    path = tmp_path / "prune.yaml"
    path.write_text("fit_threshold: 55\nenable_stale: false\n", encoding="utf-8")
    cfg = load_prune_config(path)
    assert cfg.fit_threshold == 55
    assert cfg.enable_stale is False
    assert cfg.stale_days == 60  # untouched default


def test_is_a_pydantic_model_copy_updates():
    cfg = PruneConfig().model_copy(update={"fit_threshold": 10})
    assert cfg.fit_threshold == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prune_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.tracking.prune_config'`

- [ ] **Step 3: Implement the config**

Create `src/resume_agent/tracking/prune_config.py`:

```python
from pathlib import Path

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class PruneConfig(ExtensibleModel):
    """Thresholds for auto-prune and the retention sweep (config/prune.yaml)."""

    fit_threshold: int = 40
    stale_days: int = 60
    retention_days: int = 30
    enable_rejected: bool = True
    enable_low_fit: bool = True
    enable_stale: bool = True


def load_prune_config(path: str | Path) -> PruneConfig:
    """Load prune config, returning defaults when the file is absent."""
    if not Path(path).exists():
        return PruneConfig()
    return PruneConfig.model_validate(load_yaml(path))
```

- [ ] **Step 4: Create the example config**

Create `config/prune.yaml.example`:

```yaml
# config/prune.yaml — auto-prune and retention policy.
# Copy to config/prune.yaml to override. Missing file = these defaults.

# A job is archived (reversible) if it matches ANY enabled rule below AND has no
# user progress (no application/resume version/cover letter, status not advanced).
fit_threshold: 40 # archive scored jobs with fit_score below this
stale_days: 60 # archive jobs whose posting is older than this many days
retention_days: 30 # hard-delete archived zero-progress jobs after this many days

enable_rejected: true # archive jobs the discovery filter already rejected
enable_low_fit: true # archive jobs below fit_threshold
enable_stale: true # archive jobs older than stale_days
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prune_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tracking/prune_config.py config/prune.yaml.example tests/test_prune_config.py
git commit -m "Add PruneConfig with YAML loader and example"
```

---

## Task 7: Pure prune predicates

**Files:**

- Create: `src/resume_agent/tracking/prune.py`
- Test: `tests/test_prune.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prune.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prune.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.tracking.prune'`

- [ ] **Step 3: Implement the pure predicates**

Create `src/resume_agent/tracking/prune.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prune.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/prune.py tests/test_prune.py
git commit -m "Add pure prune and expire predicates"
```

---

## Task 8: `prune_preview` + `prune_run` orchestrators

**Files:**

- Modify: `src/resume_agent/tracking/repository.py`
- Test: `tests/test_prune_run.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prune_run.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.prune_config import PruneConfig
from resume_agent.tracking.repository import (
    get_job, prune_preview, prune_run, save_application, save_job,
)
from resume_agent.tracking.tables import Application, Job, JobStatus

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value):
    assert value is not None
    return value


def test_prune_run_archives_junk_expires_old_and_skips_progress():
    cfg = PruneConfig()
    with _session() as s:
        rejected = save_job(s, Job(source="m", jd_text="a", status=JobStatus.rejected.value))
        protected = save_job(s, Job(source="m", jd_text="b", status=JobStatus.rejected.value))
        save_application(s, Application(job_id=_require_id(protected.id)))
        old_archived = save_job(s, Job(source="m", jd_text="c", status=JobStatus.raw.value,
                                       archived_at=NOW - timedelta(days=45)))

        preview = prune_preview(s, cfg, now=NOW)
        assert preview.archived == 1 and preview.expired == 1 and preview.skipped == 1
        assert preview.rejected == 1 and preview.low_fit == 0 and preview.stale == 0
        # Preview must not mutate.
        assert get_job(s, _require_id(rejected.id)).archived_at is None

        report = prune_run(s, cfg, now=NOW)
        assert report.archived == 1 and report.expired == 1 and report.skipped == 1
        assert report.rejected == 1 and report.low_fit == 0 and report.stale == 0
        assert get_job(s, _require_id(rejected.id)).archived_at is not None
        assert get_job(s, _require_id(old_archived.id)) is None       # expired
        assert get_job(s, _require_id(protected.id)) is not None      # progress kept
        assert get_job(s, _require_id(protected.id)).archived_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prune_run.py -v`
Expected: FAIL with `ImportError: cannot import name 'prune_preview'`

- [ ] **Step 3: Implement the orchestrators**

In `src/resume_agent/tracking/repository.py`, add the import near the other tracking imports:

```python
from resume_agent.tracking.prune import (
    PruneReport,
    PruneRow,
    expire_candidates,
    prune_candidates,
    prune_reason_counts,
    prune_skipped,
)
from resume_agent.tracking.prune_config import PruneConfig
```

Add:

```python
def _prune_rows(session: Session) -> list[PruneRow]:
    rows: list[PruneRow] = []
    for job in session.exec(select(Job)).all():
        if job.id is None:
            continue
        rows.append(
            PruneRow(
                job_id=job.id,
                status=job.status,
                fit_score=job.fit_score,
                posted_at=job.posted_at,
                created_at=job.created_at,
                archived_at=job.archived_at,
                has_progress=has_progress(session, job.id),
            )
        )
    return rows


def _prune_plan(session: Session, config: PruneConfig, now: datetime):
    rows = _prune_rows(session)
    return (
        prune_candidates(rows, config, now),
        expire_candidates(rows, config, now),
        prune_skipped(rows, config, now),
    )


def _prune_report(
    to_archive: list[PruneRow],
    to_expire: list[PruneRow],
    skipped: list[PruneRow],
    config: PruneConfig,
    now: datetime,
) -> PruneReport:
    reasons = prune_reason_counts(to_archive, config, now)
    return PruneReport(
        archived=len(to_archive),
        expired=len(to_expire),
        skipped=len(skipped),
        rejected=reasons["rejected"],
        low_fit=reasons["low_fit"],
        stale=reasons["stale"],
    )


def prune_preview(
    session: Session, config: PruneConfig, now: datetime | None = None
) -> PruneReport:
    """Count what a prune would do, without writing anything."""
    now = now or utcnow()
    to_archive, to_expire, skipped = _prune_plan(session, config, now)
    return _prune_report(to_archive, to_expire, skipped, config, now)


def prune_run(
    session: Session, config: PruneConfig, now: datetime | None = None
) -> PruneReport:
    """Archive matching junk and expire old archived rows. Returns the tally."""
    now = now or utcnow()
    to_archive, to_expire, skipped = _prune_plan(session, config, now)
    for row in to_archive:
        archive_job(session, row.job_id)
    for row in to_expire:
        delete_job(session, row.job_id)
    return _prune_report(to_archive, to_expire, skipped, config, now)
```

Also add `from datetime import datetime` at the top of `repository.py` if not already imported (it currently is not — add it).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prune_run.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/repository.py tests/test_prune_run.py
git commit -m "Add prune_preview and prune_run orchestrators"
```

---

## Task 9: `resume-agent prune` CLI command

**Files:**

- Modify: `src/resume_agent/cli.py`
- Test: `tests/test_cli_prune.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_prune.py`:

```python
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus

runner = CliRunner()


def _seed(db_url: str) -> None:
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        save_job(s, Job(source="m", jd_text="a", status=JobStatus.rejected.value))


def test_prune_dry_run_changes_nothing(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed(db_url)
    result = runner.invoke(cli.app, ["prune", "--db-url", db_url, "--dry-run",
                                     "--config", str(tmp_path / "absent.yaml")])
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower()

    engine = make_engine(db_url)
    with get_session(engine) as s:
        from sqlmodel import select
        job = s.exec(select(Job)).first()
        assert job is not None and job.archived_at is None


def test_prune_applies_and_reports(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed(db_url)
    result = runner.invoke(cli.app, ["prune", "--db-url", db_url,
                                     "--config", str(tmp_path / "absent.yaml")])
    assert result.exit_code == 0, result.output
    assert "archived" in result.output.lower()

    engine = make_engine(db_url)
    with get_session(engine) as s:
        from sqlmodel import select
        job = s.exec(select(Job)).first()
        assert job is not None and job.archived_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_prune.py -v`
Expected: FAIL (no `prune` command → non-zero exit / usage error)

- [ ] **Step 3: Implement the command**

In `src/resume_agent/cli.py`, extend the existing repository import (line ~41) to add `prune_preview, prune_run`, and add the config import:

```python
from resume_agent.tracking.repository import (
    get_job, jobs_by_status, prune_preview, prune_run, save_job, update_application_status,
)
from resume_agent.tracking.prune_config import load_prune_config
```

`_engine` (which does `make_engine` + `init_db`), `get_session`, and `get_settings` are already imported in `cli.py` — reuse `_engine`, don't duplicate engine setup.

Add the command (place it near the other top-level `@app.command()` functions):

```python
@app.command()
def prune(
    db_url: str | None = typer.Option(None, "--db-url", help="Override the configured DB URL."),
    config: str = typer.Option("config/prune.yaml", "--config", help="Path to prune.yaml."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show counts without writing."),
    fit: int | None = typer.Option(None, "--fit", help="Override fit_threshold."),
    stale_days: int | None = typer.Option(None, "--stale-days", help="Override stale_days."),
    retention_days: int | None = typer.Option(None, "--retention-days", help="Override retention_days."),
) -> None:
    """Archive junk jobs (rejected / low-fit / stale) and expire old archived ones."""
    cfg = load_prune_config(config)
    overrides = {
        k: v
        for k, v in (
            ("fit_threshold", fit),
            ("stale_days", stale_days),
            ("retention_days", retention_days),
        )
        if v is not None
    }
    if overrides:
        cfg = cfg.model_copy(update=overrides)

    with get_session(_engine(db_url)) as session:
        if dry_run:
            report = prune_preview(session, cfg)
            typer.echo(
                f"[dry-run] {report.rejected} rejected, {report.low_fit} low-fit, "
                f"{report.stale} stale -> {report.archived} to archive; "
                f"{report.expired} to expire, "
                f"{report.skipped} skipped (have progress)"
            )
        else:
            report = prune_run(session, cfg)
            typer.echo(
                f"+{report.archived} archived "
                f"({report.rejected} rejected, {report.low_fit} low-fit, {report.stale} stale), "
                f"{report.expired} expired, "
                f"{report.skipped} skipped"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_prune.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_prune.py
git commit -m "Add resume-agent prune CLI command"
```

---

## Task 10: `triage_rows` + `archived_rows` builders

**Files:**

- Modify: `src/resume_agent/tracking/queries.py`
- Test: `tests/test_tracking_queries.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tracking_queries.py`:

```python
def test_triage_rows_are_pre_shortlist_and_unarchived():
    from resume_agent.tracking.queries import triage_rows
    from resume_agent.tracking.repository import archive_job

    with _session() as s:
        save_job(s, Job(source="m", jd_text="a", company="Raw", title="E",
                        status=JobStatus.raw.value, fit_score=30))
        save_job(s, Job(source="m", jd_text="b", company="Rej", title="E",
                        status=JobStatus.rejected.value))
        save_job(s, Job(source="m", jd_text="c", company="Short", title="E",
                        status=JobStatus.shortlisted.value))  # excluded: has own page
        hidden = save_job(s, Job(source="m", jd_text="d", company="Hidden", title="E",
                                 status=JobStatus.raw.value))
        archive_job(s, _require_id(hidden.id))

        companies = {r.company for r in triage_rows(s)}
        assert companies == {"Raw", "Rej"}


def test_archived_rows_lists_all_archived_any_status():
    from resume_agent.tracking.queries import archived_rows
    from resume_agent.tracking.repository import archive_job

    with _session() as s:
        a = save_job(s, Job(source="m", jd_text="a", company="A", title="E",
                            status=JobStatus.shortlisted.value))
        b = save_job(s, Job(source="m", jd_text="b", company="B", title="E",
                            status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="c", company="C", title="E",
                        status=JobStatus.raw.value))  # not archived
        archive_job(s, _require_id(a.id))
        archive_job(s, _require_id(b.id))

        assert {r.company for r in archived_rows(s)} == {"A", "B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py::test_triage_rows_are_pre_shortlist_and_unarchived tests/test_tracking_queries.py::test_archived_rows_lists_all_archived_any_status -v`
Expected: FAIL with `ImportError: cannot import name 'triage_rows'`

- [ ] **Step 3: Implement the builders**

In `src/resume_agent/tracking/queries.py`, add the dataclass after `PipelineRow`:

```python
@dataclass
class TriageRow:
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    source: str
    status: str
    fit_score: int | None
    posted_at: datetime | None
    archived_at: datetime | None
    has_progress: bool
```

Add the builders (import `has_progress` from repository at the top — note `queries.py` already imports from `repository`, so extend that import):

```python
_TRIAGE_STATUSES = (
    JobStatus.raw.value,
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
)


def _triage_row(session: Session, job: Job) -> TriageRow:
    job_id = _require_job_id(job)
    return TriageRow(
        job_id=job_id,
        company=job.company,
        title=job.title,
        location=job.location,
        source=job.source,
        status=job.status,
        fit_score=job.fit_score,
        posted_at=job.posted_at,
        archived_at=job.archived_at,
        has_progress=has_progress(session, job_id),
    )


def triage_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    status_col = cast(Any, Job.status)
    jobs = session.exec(
        select(Job)
        .where(status_col.in_(_TRIAGE_STATUSES), archived_col.is_(None))
        .order_by(cast(Any, Job.fit_score).asc().nullsfirst())
    ).all()
    return [_triage_row(session, job) for job in jobs]


def archived_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job).where(archived_col.is_not(None)).order_by(archived_col.desc())
    ).all()
    return [_triage_row(session, job) for job in jobs]
```

Update the repository import in `queries.py` to include `has_progress`:

```python
from resume_agent.tracking.repository import (
    application_for_job,
    has_progress,
    latest_rendered_resume_version,
    latest_resume_version,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/queries.py tests/test_tracking_queries.py
git commit -m "Add triage_rows and archived_rows builders"
```

---

## Task 11: Pure selection-state helper

**Files:**

- Create: `src/resume_agent/dashboard/selection.py`
- Test: `tests/test_dashboard_selection.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_selection.py`:

```python
from resume_agent.dashboard.selection import all_deletable


def test_all_deletable_requires_nonempty_subset():
    assert all_deletable({1, 2}, {1, 2, 3}) is True
    assert all_deletable({1, 9}, {1, 2, 3}) is False   # 9 not deletable
    assert all_deletable(set(), {1, 2}) is False        # nothing selected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_selection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.dashboard.selection'`

- [ ] **Step 3: Implement**

Create `src/resume_agent/dashboard/selection.py`:

```python
"""Pure helper for the Triage page's bulk-delete gate.

Kept Streamlit-free so the rule is unit-testable; the render layer derives the
selected ids directly from the per-card checkbox widget state.
"""


def all_deletable(selected_ids: set[int], deletable_ids: set[int]) -> bool:
    """True only if something is selected and every selected job may be hard-deleted."""
    return bool(selected_ids) and selected_ids <= deletable_ids
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_selection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/dashboard/selection.py tests/test_dashboard_selection.py
git commit -m "Add pure Triage selection helpers"
```

---

## Task 12: Triage page (render + prune panel + nav)

**Files:**

- Modify: `src/resume_agent/dashboard/pages.py`
- Modify: `src/resume_agent/dashboard/app.py`
- Test: `tests/test_dashboard_app.py`

> **Note on UI testing:** Streamlit render functions are verified the way this repo
> already does it — a callable-exposure assertion plus an `AppTest` smoke run. The
> behavioral logic (row builders, selection, prune) is already unit-tested in
> Tasks 7–11, so these steps focus on wiring without regressions.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_app.py`:

```python
def test_dashboard_exposes_triage_page():
    from resume_agent.dashboard import app
    assert callable(app.render_triage_page)


def test_triage_page_renders_with_a_raw_job(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import resume_agent.dashboard.app as appmod
    from resume_agent.config import get_settings
    from resume_agent.db import get_session, init_db, make_engine
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job, JobStatus

    db_url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    monkeypatch.setenv("DB_URL", db_url)
    get_settings.cache_clear()

    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                        status=JobStatus.raw.value, fit_score=20))
    try:
        at = AppTest.from_file(appmod.__file__, default_timeout=30).run()
        at.radio[0].set_value("Triage").run()
        assert not at.exception, at.exception
        assert any(widget.label == "Status" for widget in at.multiselect)
        assert any(widget.label == "Sort by" for widget in at.selectbox)
    finally:
        get_settings.cache_clear()  # don't leak the temp DB into other tests
```

> Seed pattern copied verbatim from the repo's existing
> `test_dashboard_pages_render_without_error`: the settings env var is `DB_URL`
> and `get_settings` is `@lru_cache`'d, so `cache_clear()` before and after is
> mandatory. Sidebar radio is reached as `at.radio[0]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_app.py::test_dashboard_exposes_triage_page -v`
Expected: FAIL with `AttributeError: module 'resume_agent.dashboard.app' has no attribute 'render_triage_page'`

- [ ] **Step 3: Implement the Triage page**

Add to `src/resume_agent/dashboard/pages.py`. Update imports at the top:

```python
from datetime import datetime, timezone

from resume_agent.dashboard.selection import all_deletable
from resume_agent.tracking.prune_config import load_prune_config
from resume_agent.tracking.queries import (
    PipelineRow, TriageRow, archived_rows, pipeline_rows, shortlist_rows, triage_rows,
)
from resume_agent.tracking.repository import (
    application_for_job, archive_job, delete_job, get_job, prune_preview, prune_run,
    restore_job, save_application, save_job, update_application_status,
)
```

Add the constant and helpers:

```python
_PRUNE_CONFIG_PATH = "config/prune.yaml"
_UNDO_KEY = "triage_last_archived"


def _triage_card(row: TriageRow) -> bool:
    """Render one triage card; return whether its checkbox is ticked.

    The checkbox's own keyed widget state (``sel-{id}``) is the single source of
    truth — there is no parallel selection set to drift out of sync.
    """
    with st.container(border=True):
        head, box = st.columns([5, 1], vertical_alignment="center")
        with head:
            st.markdown(
                f'<div class="card-title">{row.title or "—"}</div>'
                f'<div class="card-meta">{row.company or "—"} · '
                f'{row.location or "location n/a"} &nbsp; {status_badge(row.status)}</div>'
                f'<div class="metaline">fit {row.fit_score if row.fit_score is not None else "—"} '
                f'· {row.source}</div>',
                unsafe_allow_html=True,
            )
        with box:
            checked = st.checkbox("Select", key=f"sel-{row.job_id}",
                                  label_visibility="collapsed")
    return checked


def _clear_checkboxes(job_ids) -> None:
    # Acted-on rows leave the view; drop their stale checkbox state so a later
    # "Show archived" toggle can't resurrect a ticked box for the same id.
    for jid in job_ids:
        st.session_state.pop(f"sel-{jid}", None)


def _row_age_days(row: TriageRow) -> int | None:
    if row.posted_at is None:
        return None
    posted = row.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    else:
        posted = posted.astimezone(timezone.utc)
    return max(0, (datetime.now(timezone.utc) - posted).days)


def _filter_sort_triage_rows(rows: list[TriageRow]) -> list[TriageRow]:
    with st.container(key="controldesk_triage"):
        st.markdown('<div class="controldesk-head">Filter &amp; sort</div>',
                    unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4, gap="medium", vertical_alignment="top")
        statuses = sorted({row.status for row in rows})
        chosen = set(c1.multiselect("Status", statuses, default=statuses, key="triage_status"))
        min_fit = c2.slider("Min fit", 0, 100, 0, key="triage_min_fit")
        max_age = c3.number_input("Max age days (0 = any)", 0, 3650, 0, key="triage_max_age")
        sort = c4.selectbox("Sort by", ["fit", "recency", "company"], key="triage_sort")

    visible = []
    for row in rows:
        age = _row_age_days(row)
        if row.status not in chosen:
            continue
        if row.fit_score is not None and row.fit_score < min_fit:
            continue
        if max_age and age is not None and age > max_age:
            continue
        visible.append(row)

    if sort == "fit":
        visible.sort(key=lambda row: (row.fit_score is not None, row.fit_score or -1),
                     reverse=True)
    elif sort == "recency":
        visible.sort(key=lambda row: _row_age_days(row) if _row_age_days(row) is not None else 10**9)
    else:
        visible.sort(key=lambda row: ((row.company or "").lower(), (row.title or "").lower()))
    return visible


def _render_archive_undo(session) -> None:
    last_archived = list(st.session_state.get(_UNDO_KEY, []))
    if not last_archived:
        return
    msg, action = st.columns([3, 1], vertical_alignment="center")
    msg.success(f"Archived {len(last_archived)} job(s).")
    if action.button("Undo archive", key="triage_undo_archive"):
        for jid in last_archived:
            restore_job(session, jid)
        st.session_state[_UNDO_KEY] = []
        _clear_checkboxes(last_archived)
        st.rerun()


def render_triage_page(session) -> None:
    masthead(
        "Intake",
        'Triage <span class="dot">·</span> Desk',
        "Raw and rejected jobs before the shortlist. Archive noise, delete dead-ends, prune in bulk.",
    )

    show_archived = st.toggle("Show archived", value=False, key="triage_show_archived")
    rows = archived_rows(session) if show_archived else triage_rows(session)
    _render_archive_undo(session)

    if not rows:
        empty_state("◇", "Nothing to triage",
                    "Run <code>resume-agent pull</code> to bring in jobs, or toggle archived.")
        return

    visible = _filter_sort_triage_rows(rows)
    metric_row([("In view", str(len(visible))),
                ("Deletable", str(sum(1 for r in visible if not r.has_progress)))])

    _render_prune_panel(session)

    if not visible:
        empty_state("◇", "No jobs match these filters", "Loosen a filter or clear the age limit.")
        return

    # Derive the selection straight from the per-card checkboxes as we render them.
    selected: set[int] = set()
    with st.container(key="cardgrid_triage"):
        for row in visible:
            if _triage_card(row):
                selected.add(row.job_id)

    deletable_ids = {r.job_id for r in visible if not r.has_progress}
    _render_action_bar(session, selected, deletable_ids, show_archived)


def _render_action_bar(session, selected, deletable_ids, show_archived) -> None:
    with st.container(key="triage_actionbar"):
        cols = st.columns(2)
        if show_archived:
            if cols[0].button("Restore selected", key="triage_restore", disabled=not selected):
                for jid in selected:
                    restore_job(session, jid)
                _clear_checkboxes(selected)
                st.rerun()
            return
        if cols[0].button("Archive selected", key="triage_archive", disabled=not selected):
            archived = sorted(selected)
            for jid in archived:
                archive_job(session, jid)
            st.session_state[_UNDO_KEY] = archived
            _clear_checkboxes(archived)
            st.rerun()
        if cols[1].button("Delete selected", key="triage_delete",
                          disabled=not all_deletable(selected, deletable_ids)):
            _confirm_delete(session, sorted(selected))


@st.dialog("Permanently delete jobs")
def _confirm_delete(session, job_ids: list[int]) -> None:
    st.write(f"Delete {len(job_ids)} job(s)? This cannot be undone.")
    if st.button("Confirm delete", key="confirm_delete"):
        for jid in job_ids:
            delete_job(session, jid)
        _clear_checkboxes(job_ids)
        st.rerun()


def _render_prune_panel(session) -> None:
    config = load_prune_config(_PRUNE_CONFIG_PATH)
    with st.expander("Prune (archive junk, expire old)"):
        c1, c2, c3 = st.columns(3)
        fit = c1.number_input("Fit below", 0, 100, config.fit_threshold, key="prune_fit")
        stale = c2.number_input("Stale days", 0, 3650, config.stale_days, key="prune_stale")
        retain = c3.number_input("Retention days", 0, 3650, config.retention_days, key="prune_retain")
        run_config = config.model_copy(
            update={"fit_threshold": fit, "stale_days": stale, "retention_days": retain}
        )
        preview = prune_preview(session, run_config)
        st.caption(
            f"{preview.rejected} rejected · {preview.low_fit} low-fit · {preview.stale} stale "
            f"→ {preview.archived} archive · {preview.expired} expire · "
            f"{preview.skipped} skipped (have progress)"
        )
        if st.button("Prune now", key="prune_now"):
            _confirm_prune(session, run_config)


@st.dialog("Run prune")
def _confirm_prune(session, run_config) -> None:
    report = prune_preview(session, run_config)
    st.write(
        f"Archive {report.archived} job(s) and permanently delete {report.expired} "
        "expired archived job(s)? Expiry cannot be undone."
    )
    if st.button("Confirm prune", key="confirm_prune"):
        prune_run(session, run_config)
        st.rerun()
```

- [ ] **Step 4: Add the grid CSS**

In `src/resume_agent/dashboard/ui.py`, after the `st-key-cardgrid_shortlist` grid rule (around line 80), add a triage grid that matches the shortlist grid:

```css
div[data-testid="stVerticalBlock"][class*="st-key-cardgrid_triage"] {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 480px), 1fr));
  gap: clamp(1rem, 1.4vw, 1.6rem);
  align-items: stretch;
}

div[data-testid="stVerticalBlock"][class*="st-key-triage_actionbar"] {
  position: sticky;
  bottom: 1rem;
  z-index: 5;
  background: var(--paper-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: 0.7rem;
  box-shadow: 0 4px 18px rgba(22, 19, 15, 0.12);
}
```

- [ ] **Step 5: Wire nav + routing in `app.py`**

In `src/resume_agent/dashboard/app.py`, add `render_triage_page` to the `pages` import, add `"Triage"` to the radio options, and route it:

```python
from resume_agent.dashboard.pages import (  # noqa: F401  (re-exported)
    analytics_table_rows,
    match_gap_table_rows,
    render_analytics_page,
    render_match_gap_page,
    render_pipeline_page,
    render_shortlist_page,
    render_triage_page,
)
```

```python
        page = st.radio(
            "View",
            ["Shortlist", "Triage", "Pipeline board", "Analytics", "Match-gap"],
            label_visibility="collapsed",
        )
```

```python
        if page == "Shortlist":
            render_shortlist_page(session)
        elif page == "Triage":
            render_triage_page(session)
        elif page == "Pipeline board":
            render_pipeline_page(session)
        elif page == "Analytics":
            render_analytics_page(session)
        else:
            render_match_gap_page(session)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_app.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/dashboard/pages.py src/resume_agent/dashboard/app.py src/resume_agent/dashboard/ui.py tests/test_dashboard_app.py
git commit -m "Add Triage filtering, bulk actions, undo, restore, and prune panel"
```

---

## Task 13: Pipeline board controls

**Files:**

- Modify: `src/resume_agent/dashboard/pages.py`
- Test: `tests/test_dashboard_app.py`

> Adds a filter/sort control desk, collapsible stage groups, and per-card archive,
> delete (only when `not row.has_progress`), and manual JobStatus stage controls.
> `PipelineRow` gains a `has_progress` flag so the delete button can be gated
> without a second query.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_app.py`:

```python
def test_pipeline_row_carries_has_progress_flag():
    from sqlmodel import Session, SQLModel, create_engine
    from resume_agent.tracking.queries import pipeline_rows
    from resume_agent.tracking.repository import save_application, save_job
    from resume_agent.tracking.tables import Application, Job, JobStatus

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        raw = save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        adv = save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        assert adv.id is not None
        save_application(s, Application(job_id=adv.id))

        flags = {r.job_id: r.has_progress for r in pipeline_rows(s)}
        assert flags[raw.id] is False
        assert flags[adv.id] is True
```

Also extend the existing `test_dashboard_pages_render_without_error` after the
Pipeline navigation to prove the new control desk is wired:

```python
        assert any(widget.label == "Stages" for widget in at.multiselect)
        assert any(widget.label == "Sort by" for widget in at.selectbox)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_app.py::test_pipeline_row_carries_has_progress_flag -v`
Expected: FAIL with `AttributeError: 'PipelineRow' object has no attribute 'has_progress'`

- [ ] **Step 3: Add `has_progress` to `PipelineRow`**

In `src/resume_agent/tracking/queries.py`, add the field to the `PipelineRow` dataclass (after `seniority`):

```python
    has_progress: bool = False
```

In `pipeline_rows`, set it when building each row (inside the `PipelineRow(...)` constructor):

```python
                has_progress=has_progress(session, job_id),
```

`has_progress` is already imported into `queries.py` from Task 10.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_app.py::test_pipeline_row_carries_has_progress_flag -v`
Expected: PASS

- [ ] **Step 5: Add the controls to `_render_pipeline_card`**

In `src/resume_agent/dashboard/pages.py`, inside `_render_pipeline_card`, after the existing "Save status" block, add stage-change + archive/delete controls:

```python
        st.markdown('<div class="rail-head">Manage</div>', unsafe_allow_html=True)
        stage_col, arch_col, del_col = st.columns([2, 1, 1])
        with stage_col:
            stages = [s.value for s in JobStatus]
            new_stage = st.selectbox(
                "Stage", stages, index=stages.index(row.status), key=f"stage-{row.job_id}"
            )
            if st.button("Set stage", key=f"setstage-{row.job_id}"):
                job = get_job(session, row.job_id)
                if job is not None:
                    job.status = new_stage
                    save_job(session, job)
                    st.rerun()
        with arch_col:
            if st.button("Archive", key=f"arch-{row.job_id}"):
                archive_job(session, row.job_id)
                st.session_state[_UNDO_KEY] = [row.job_id]
                st.rerun()
        with del_col:
            if not row.has_progress and st.button("Delete", key=f"del-{row.job_id}"):
                _confirm_delete(session, [row.job_id])
```

- [ ] **Step 6: Add the Pipeline filter/sort desk**

Add a small page-local helper in `src/resume_agent/dashboard/pages.py`:

```python
def _filter_sort_pipeline_rows(rows: list[PipelineRow]) -> list[PipelineRow]:
    with st.container(key="controldesk_pipeline"):
        st.markdown('<div class="controldesk-head">Filter &amp; sort</div>',
                    unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4, gap="medium", vertical_alignment="top")
        statuses = sorted({row.status for row in rows})
        chosen = set(c1.multiselect("Stages", statuses, default=statuses, key="pipe_stages"))
        min_fit = c2.slider("Min fit", 0, 100, 0, key="pipe_min_fit")
        query = c3.text_input("Company/title", key="pipe_query")
        sort = c4.selectbox("Sort by", ["stage", "fit", "company"], key="pipe_sort")

    needle = query.strip().lower()
    visible = []
    for row in rows:
        haystack = f"{row.company or ''} {row.title or ''}".lower()
        if row.status not in chosen:
            continue
        if row.fit_score is not None and row.fit_score < min_fit:
            continue
        if needle and needle not in haystack:
            continue
        visible.append(row)

    if sort == "fit":
        visible.sort(key=lambda row: (row.fit_score is not None, row.fit_score or -1),
                     reverse=True)
    elif sort == "company":
        visible.sort(key=lambda row: ((row.company or "").lower(), (row.title or "").lower()))
    else:
        order = {status: idx for idx, status in enumerate(_STATUS_ORDER)}
        visible.sort(key=lambda row: (order.get(row.status, 999),
                                      (row.company or "").lower(), (row.title or "").lower()))
    return visible
```

- [ ] **Step 7: Add collapsible stage groups in `render_pipeline_page`**

In `render_pipeline_page`, call `_render_archive_undo(session)`, filter the rows
before counting, and wrap each status section's card grid in an `st.expander`:

```python
    _render_archive_undo(session)
    rows = _filter_sort_pipeline_rows(rows)
    if not rows:
        empty_state("◇", "No jobs match these filters", "Loosen a Pipeline filter.")
        return
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    rendered = counts.get(JobStatus.rendered.value, 0)
    metric_row([("In view", str(len(rows))), ("Rendered", str(rendered)),
                ("Stages active", str(len(counts)))])
    present = [s for s in _STATUS_ORDER if s in counts]
    present += [s for s in counts if s not in _STATUS_ORDER]

    for status in present:
        with st.expander(f"{status} · {counts[status]}", expanded=status != JobStatus.rejected.value):
            with st.container(key=f"cardgrid_pipeline_{status}"):
                for row in [r for r in rows if r.status == status]:
                    _render_pipeline_card(session, row)
```

- [ ] **Step 8: Run the dashboard + queries suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_app.py tests/test_tracking_queries.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/resume_agent/dashboard/pages.py src/resume_agent/tracking/queries.py tests/test_dashboard_app.py
git commit -m "Add pipeline board filtering, archive/delete, stage change, and collapsible groups"
```

---

## Task 14: Full suite + lint + docs

**Files:**

- Modify: `CLAUDE.md`
- Test: full suite

- [ ] **Step 1: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (all tests, including the pre-existing suite)

- [ ] **Step 2: Lint**

Run: `ruff check`
Expected: no errors. Fix any reported issues (unused imports, line length) in the files you touched only.

- [ ] **Step 3: Document the new behavior in `CLAUDE.md`**

Add a short subsection under "Core invariants" documenting the archive/delete/prune model:

```markdown
### Archive, delete, prune

`Job.archived_at` (orthogonal to `status`) soft-hides a job; every view filters
`archived_at IS NULL` except dedupe lookup, which intentionally still sees trash-bin
jobs to avoid duplicate re-ingest. `has_progress(session, job_id)` — status in
{approved, tailored, rendered} OR any Application/ResumeVersion/CoverLetter — is
the single gate for irreversible paths. `delete_job` refuses jobs with progress and
cascades incidental children in FK-safe order otherwise. `prune_run` (config:
`config/prune.yaml`) archives rejected/low-fit/stale zero-progress jobs, reports
primary reason counts, then hard-deletes archived zero-progress jobs older than
`retention_days`. Surfaced via the dashboard Triage page and
`resume-agent prune [--dry-run]`.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Document archive/delete/prune model in CLAUDE.md"
```

---

## Self-Review

- **Spec coverage:** D1 tiered (Tasks 2/4) · D2 `archived_at` (Task 1) · D3 trash-bin (Tasks 7/8) · D4 criteria + reason counts (Tasks 7/8) · D5 trigger button+CLI (Tasks 9/12) · D6 YAML+override (Tasks 6/9/12) · D7 Triage page (Task 12) · D8 checkbox cards + sticky action bar + restore (Tasks 11/12) · D9 pipeline filter/sort + controls + collapsible groups (Task 13) · D10 asymmetric confirm + archive undo (Tasks 12/13). All covered.
- **Blast radius (spec §3):** archived filter on shortlist/pipeline/status_counts/jobs_by_status/application_job_pairs/match-gap/analytics — Task 5. Tested. Dedupe lookup remains intentionally unfiltered.
- **Type consistency:** `PruneRow`/`PruneReport`/`PruneConfig`, `triage_rows`/`archived_rows`/`TriageRow`, `has_progress`, `archive_job`/`restore_job`/`delete_job`, `prune_preview`/`prune_run` used with identical signatures across tasks.
- **AppTest seeding:** Task 12's render test uses the repo's verified pattern (`DB_URL` env var + `get_settings.cache_clear()` in a `try/finally`), copied from `test_dashboard_pages_render_without_error`.

```

```
