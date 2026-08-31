# Résumé Tailor Harness — Tracking (SQLite + Streamlit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the human one place to drive the pipeline: an `applications` repository layer + read-model query functions, plus a **Streamlit** dashboard with two pages — a **Shortlist** page (the approve checkpoint) and a **Pipeline board** (status, fit score, open-PDF link, JD + critiques, editable application status/notes). Also close the deferred Foundation item (`applications.updated_at` auto-bump on update).

**Architecture:** All data logic lives in **testable, Streamlit-free** functions (`tracking/repository.py` for writes, `tracking/queries.py` for read-models returning plain dataclasses). `dashboard/app.py` is a **thin** view that only calls those functions, so the test weight sits on pure Python; the Streamlit script gets an import smoke test plus a documented manual-verification step. The `dashboard` CLI command shells out to `streamlit run`, passing the DB URL through the environment.

**Tech Stack:** Python 3.13, uv, **streamlit** (new dep), SQLModel, Typer, pytest. (Dashboard reads the same SQLite DB that every other stage writes.)

**Depends on:** Foundation (`tracking.tables.Job/ResumeVersion/Application`, `JobStatus`, `ApplicationStatus`, `utcnow`, `db`), Discovery (`tracking.repository`), Tailor + Review (`resume_versions`), Render (`resume_versions.pdf_path`). All merged to `main`.

> **Commit convention:** every commit ends with a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Reference & scoped decisions

Design spec §5.5. Decisions for this plan:

- **Two status lifecycles stay separate:** `jobs.status` (pipeline) vs `applications.status` (employer funnel) — already modeled in Foundation; this plan adds the `applications` repository + the UI that drives both.
- **Logic out of the view:** every query/mutation is a plain function unit-tested against in-memory SQLite. `dashboard/app.py` contains no business logic worth testing beyond wiring.
- **DB URL via env:** the Streamlit script resolves the DB from `Settings.db_url` (env `DB_URL`), so the CLI can point it at any database by setting that variable for the subprocess. No Streamlit-specific config.
- **Deferred Foundation item:** add `onupdate=utcnow` to `applications.updated_at` (tz-aware datetimes were already satisfied by `utcnow()`).

## File Structure (created/modified)

```
pyproject.toml                       # MODIFY: add `streamlit` dependency
src/resume_tailor_harness/
  tracking/
    tables.py                        # MODIFY: applications.updated_at onupdate
    repository.py                    # MODIFY: application CRUD + latest_resume_version
    queries.py                       # CREATE: ShortlistRow/PipelineRow + read-models
  dashboard/
    __init__.py                      # CREATE
    app.py                           # CREATE: thin Streamlit two-page view
  cli.py                             # MODIFY: add `dashboard` command
tests/
  test_tables_onupdate.py
  test_applications_repository.py
  test_tracking_queries.py
  test_dashboard_app.py
  test_cli_dashboard.py
```

---

## Task 1: `applications.updated_at` auto-bump (deferred Foundation item)

**Files:**

- Modify: `src/resume_tailor_harness/tracking/tables.py`
- Test: `tests/test_tables_onupdate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tables_onupdate.py`:

```python
from resume_tailor_harness.tracking.tables import Application


def test_application_updated_at_has_onupdate():
    col = Application.__table__.c.updated_at
    assert col.onupdate is not None
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tables_onupdate.py -v
```

Expected: FAIL — `assert None is not None`.

- [ ] **Step 3: Implement**

In `src/resume_tailor_harness/tracking/tables.py`, change the `Application.updated_at` field:

```python
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow}
    )
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tables_onupdate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/tables.py tests/test_tables_onupdate.py
git commit -m "feat(tracking): applications.updated_at auto-bump on update" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Applications repository

**Files:**

- Modify: `src/resume_tailor_harness/tracking/repository.py`
- Test: `tests/test_applications_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_applications_repository.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.tracking.repository import (
    application_for_job,
    applications_by_status,
    get_application,
    latest_resume_version,
    latest_rendered_resume_version,
    save_application,
    save_resume_version,
    update_application_status,
)
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_application_crud_and_lookup():
    with _session() as s:
        app = save_application(s, Application(job_id=1, status=ApplicationStatus.ready.value))
        assert get_application(s, app.id).job_id == 1
        assert application_for_job(s, 1).id == app.id
        assert application_for_job(s, 999) is None
        assert [a.id for a in applications_by_status(s, ApplicationStatus.ready.value)] == [app.id]


def test_update_application_status_and_notes():
    with _session() as s:
        app = save_application(s, Application(job_id=1, status=ApplicationStatus.ready.value))
        updated = update_application_status(
            s, app.id, ApplicationStatus.submitted.value, notes="applied via portal"
        )
        assert updated.status == ApplicationStatus.submitted.value
        assert updated.notes == "applied via portal"


def test_latest_resume_version_picks_highest_round():
    with _session() as s:
        save_resume_version(s, ResumeVersion(job_id=7, round=1, content_json={"a": 1}))
        save_resume_version(s, ResumeVersion(job_id=7, round=2, content_json={"a": 2}))
        latest = latest_resume_version(s, 7)
        assert latest.round == 2
        assert latest_resume_version(s, 999) is None


def test_latest_rendered_resume_version_picks_highest_round_with_pdf():
    with _session() as s:
        save_resume_version(s, ResumeVersion(job_id=7, round=1, content_json={"a": 1}, pdf_path="one.pdf"))
        save_resume_version(s, ResumeVersion(job_id=7, round=2, content_json={"a": 2}))
        save_resume_version(s, ResumeVersion(job_id=7, round=3, content_json={"a": 3}, pdf_path="three.pdf"))
        latest = latest_rendered_resume_version(s, 7)
        assert latest.round == 3
        assert latest.pdf_path == "three.pdf"
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_applications_repository.py -v
```

Expected: FAIL — `ImportError` (`save_application`, etc. not defined).

- [ ] **Step 3: Implement**

Add to `src/resume_tailor_harness/tracking/repository.py`. First extend the tables import line:

```python
from resume_tailor_harness.tracking.tables import Application, Job, ResumeVersion
```

Then append:

```python
def save_application(session: Session, application: Application) -> Application:
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def get_application(session: Session, application_id: int) -> Application | None:
    return session.get(Application, application_id)


def application_for_job(session: Session, job_id: int) -> Application | None:
    return session.exec(select(Application).where(Application.job_id == job_id)).first()


def applications_by_status(session: Session, status: str) -> list[Application]:
    return list(session.exec(select(Application).where(Application.status == status)).all())


def update_application_status(
    session: Session, application_id: int, status: str, notes: str | None = None
) -> Application | None:
    application = session.get(Application, application_id)
    if application is None:
        return None
    application.status = status
    if notes is not None:
        application.notes = notes
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def latest_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id)
        .order_by(ResumeVersion.round.desc())
    ).first()


def latest_rendered_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id, ResumeVersion.pdf_path.is_not(None))
        .order_by(ResumeVersion.round.desc())
    ).first()
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_applications_repository.py tests/test_repository.py -v
```

Expected: PASS (new application tests + existing repository tests stay green).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/repository.py tests/test_applications_repository.py
git commit -m "feat(tracking): applications repository + latest_resume_version" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Read-model queries for the dashboard

**Files:**

- Create: `src/resume_tailor_harness/tracking/queries.py`
- Test: `tests/test_tracking_queries.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracking_queries.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.tracking.repository import save_application, save_job, save_resume_version
from resume_tailor_harness.tracking.queries import pipeline_rows, shortlist_rows
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, Job, JobStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_shortlist_rows_only_shortlisted_with_fit_and_sponsorship():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=82,
                        fit_rationale="strong python match",
                        criteria_json={"sponsorship_signal": "offered"}))
        save_job(s, Job(source="manual", jd_text="b", company="Beta", title="Dev",
                        status=JobStatus.raw.value))  # excluded

        rows = shortlist_rows(s)
        assert len(rows) == 1
        row = rows[0]
        assert row.company == "Acme"
        assert row.fit_score == 82
        assert row.fit_rationale == "strong python match"
        assert row.sponsorship_signal == "offered"


def test_pipeline_rows_include_pdf_and_application_status():
    with _session() as s:
        job = save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                              status=JobStatus.rendered.value, fit_score=90))
        save_resume_version(s, ResumeVersion(job_id=job.id, round=1, content_json={"x": 1}))
        save_resume_version(
            s,
            ResumeVersion(
                job_id=job.id,
                round=2,
                content_json={"contact": {"name": "Ada"}},
                critique_json=[{"reviewer": "fact-check", "passed": True}],
                pdf_path="output/acme.pdf",
            ),
        )
        save_application(s, Application(job_id=job.id, status=ApplicationStatus.submitted.value))

        rows = pipeline_rows(s)
        assert len(rows) == 1
        row = rows[0]
        assert row.status == JobStatus.rendered.value
        assert row.pdf_path == "output/acme.pdf"
        assert row.jd_text == "a"
        assert row.critique_json == [{"reviewer": "fact-check", "passed": True}]
        assert row.application_status == ApplicationStatus.submitted.value
        assert row.fit_score == 90
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tracking_queries.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.tracking.queries'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/tracking/queries.py`:

```python
from dataclasses import dataclass

from sqlmodel import Session, select

from resume_tailor_harness.tracking.repository import (
    application_for_job,
    latest_rendered_resume_version,
    latest_resume_version,
)
from resume_tailor_harness.tracking.tables import Job, JobStatus


@dataclass
class ShortlistRow:
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None


@dataclass
class PipelineRow:
    job_id: int
    company: str | None
    title: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None


def shortlist_rows(session: Session) -> list[ShortlistRow]:
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value)
        .order_by(Job.fit_score.desc().nullslast())
    ).all()
    rows = []
    for job in jobs:
        criteria = job.criteria_json or {}
        rows.append(
            ShortlistRow(
                job_id=job.id,
                company=job.company,
                title=job.title,
                location=job.location,
                fit_score=job.fit_score,
                fit_rationale=job.fit_rationale,
                sponsorship_signal=criteria.get("sponsorship_signal"),
            )
        )
    return rows


def pipeline_rows(session: Session) -> list[PipelineRow]:
    jobs = session.exec(select(Job).order_by(Job.status, Job.company, Job.title)).all()
    rows = []
    for job in jobs:
        version = latest_resume_version(session, job.id)
        rendered = latest_rendered_resume_version(session, job.id)
        application = application_for_job(session, job.id)
        rows.append(
            PipelineRow(
                job_id=job.id,
                company=job.company,
                title=job.title,
                status=job.status,
                fit_score=job.fit_score,
                jd_text=job.jd_text,
                critique_json=version.critique_json if version else None,
                pdf_path=rendered.pdf_path if rendered else None,
                application_status=application.status if application else None,
            )
        )
    return rows
```

`latest_resume_version` drives critiques; `latest_rendered_resume_version` drives the PDF link so a newer unrendered review round does not hide an older rendered PDF.

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tracking_queries.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/queries.py tests/test_tracking_queries.py
git commit -m "feat(tracking): shortlist + pipeline read-model queries" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Streamlit dashboard (thin view)

**Files:**

- Create: `src/resume_tailor_harness/dashboard/__init__.py`, `src/resume_tailor_harness/dashboard/app.py`
- Test: `tests/test_dashboard_app.py`

- [ ] **Step 1: Add the dependency**

Run:

```bash
uv add streamlit
```

Expected: `pyproject.toml` gains `streamlit>=...`; `uv.lock` updates; install succeeds.

- [ ] **Step 2: Write the failing test**

Create `tests/test_dashboard_app.py`:

```python
import importlib


def test_dashboard_module_exposes_render_functions():
    app = importlib.import_module("resume_tailor_harness.dashboard.app")
    # The page renderers and entrypoint exist and are callable.
    assert callable(app.render_shortlist_page)
    assert callable(app.render_pipeline_page)
    assert callable(app.main)
```

- [ ] **Step 3: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_dashboard_app.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.dashboard'`.

- [ ] **Step 4: Implement**

Create `src/resume_tailor_harness/dashboard/__init__.py`:

```python
"""Streamlit dashboard: shortlist checkpoint + pipeline board."""
```

Create `src/resume_tailor_harness/dashboard/app.py`:

```python
import streamlit as st

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.tracking.queries import pipeline_rows, shortlist_rows
from resume_tailor_harness.tracking.repository import (
    application_for_job,
    get_job,
    save_application,
    save_job,
    update_application_status,
)
from resume_tailor_harness.tracking.tables import ApplicationStatus, JobStatus


def _engine():
    engine = make_engine(get_settings().db_url)
    init_db(engine)
    return engine


def render_shortlist_page(session) -> None:
    st.header("Shortlist — approve jobs to tailor")
    rows = shortlist_rows(session)
    if not rows:
        st.info("No shortlisted jobs. Run `resume-tailor-harness discover` first.")
        return
    for row in rows:
        with st.container(border=True):
            st.subheader(f"{row.title or '—'} @ {row.company or '—'}")
            st.caption(f"{row.location or 'location n/a'} · fit {row.fit_score or '—'} · "
                       f"sponsorship: {row.sponsorship_signal or 'unknown'}")
            if row.fit_rationale:
                st.write(row.fit_rationale)
            if st.button("Approve for tailoring", key=f"approve-{row.job_id}"):
                job = get_job(session, row.job_id)
                job.status = JobStatus.approved.value
                save_job(session, job)
                st.success(f"Approved job #{row.job_id}.")
                st.rerun()


def render_pipeline_page(session) -> None:
    st.header("Pipeline board")
    rows = pipeline_rows(session)
    if not rows:
        st.info("No jobs yet.")
        return
    for status in sorted({row.status for row in rows}):
        st.subheader(status)
        for row in [r for r in rows if r.status == status]:
            with st.container(border=True):
                st.markdown(f"**{row.title or '—'} @ {row.company or '—'}**")
                st.caption(f"fit {row.fit_score or '—'} · application: {row.application_status or 'none'}")
                if row.pdf_path:
                    st.link_button("Open PDF", row.pdf_path)
                with st.expander("Job description"):
                    st.write(row.jd_text)
                with st.expander("Latest critiques"):
                    st.json(row.critique_json or [])
                statuses = [s.value for s in ApplicationStatus]
                current = row.application_status or ApplicationStatus.ready.value
                new_status = st.selectbox(
                    "Application status", statuses, index=statuses.index(current),
                    key=f"status-{row.job_id}",
                )
                notes = st.text_input("Notes", key=f"notes-{row.job_id}")
                if st.button("Save application status", key=f"save-{row.job_id}"):
                    application = application_for_job(session, row.job_id)
                    if application is None:
                        save_application(session, _new_application(row.job_id, new_status, notes))
                    else:
                        update_application_status(session, application.id, new_status, notes or None)
                    st.success("Saved.")
                    st.rerun()


def _new_application(job_id: int, status: str, notes: str):
    from resume_tailor_harness.tracking.tables import Application

    return Application(job_id=job_id, status=status, notes=notes or None)


def main() -> None:
    st.set_page_config(page_title="Résumé Tailor Harness", layout="wide")
    page = st.sidebar.radio("Page", ["Shortlist", "Pipeline board"])
    engine = _engine()
    with get_session(engine) as session:
        if page == "Shortlist":
            render_shortlist_page(session)
        else:
            render_pipeline_page(session)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_dashboard_app.py -v
```

Expected: PASS (1 test). Importing the module must not require a running Streamlit server (only function/`main` definitions execute at import).

- [ ] **Step 6: Manual verification (not in CI)**

Run:

```bash
uv run streamlit run src/resume_tailor_harness/dashboard/app.py
```

With a populated DB: confirm the Shortlist page lists shortlisted jobs and "Approve" flips one to `approved`; the Pipeline board groups jobs, shows the PDF path, and saves an application status. Stop the server when done.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/resume_tailor_harness/dashboard/__init__.py src/resume_tailor_harness/dashboard/app.py tests/test_dashboard_app.py
git commit -m "feat(tracking): Streamlit shortlist + pipeline dashboard" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CLI — `dashboard`

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_cli_dashboard.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_dashboard.py`:

```python
from typer.testing import CliRunner

from resume_tailor_harness import cli

runner = CliRunner()


def test_dashboard_launches_streamlit(monkeypatch):
    captured = {}

    def fake_run(args, env=None):
        captured["args"] = args
        captured["env"] = env
        class _CP:
            returncode = 0
        return _CP()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["dashboard", "--db-url", "sqlite:///tmp.db"])
    assert result.exit_code == 0, result.output
    assert captured["args"][0] == "streamlit"
    assert captured["args"][1] == "run"
    assert captured["args"][2].endswith("app.py")
    assert captured["env"]["DB_URL"] == "sqlite:///tmp.db"
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_cli_dashboard.py -v
```

Expected: FAIL — `AttributeError: module 'resume_tailor_harness.cli' has no attribute 'subprocess'` (or no `dashboard` command).

- [ ] **Step 3: Implement**

Add these imports at the top of `src/resume_tailor_harness/cli.py`:

```python
import os
import subprocess
```

Add the command AFTER the `render` command and BEFORE `if __name__ == "__main__":`:

```python
@app.command("dashboard")
def dashboard_cmd(
    db_url: str = typer.Option(None, help="Override the database URL for the dashboard."),
) -> None:
    """Launch the Streamlit dashboard (shortlist checkpoint + pipeline board)."""
    app_path = str(Path(__file__).parent / "dashboard" / "app.py")
    env = dict(os.environ)
    if db_url:
        env["DB_URL"] = db_url
    subprocess.run(["streamlit", "run", app_path], env=env)
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_cli_dashboard.py -v
```

Expected: PASS (1 test).

- [ ] **Step 5: Verify wiring**

Run:

```bash
uv run resume-tailor-harness dashboard --help
```

Expected: help text (exit 0).

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass (Render total + Tracking additions).

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_dashboard.py
git commit -m "feat(tracking): dashboard CLI command" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage (§5.5):** two separate status lifecycles preserved (Foundation tables; this plan drives both); `applications` table CRUD (Task 2); Streamlit two pages — Shortlist checkpoint with approve→`approved` (Task 4) and Pipeline board with status grouping, fit score, PDF link, editable application status/notes (Tasks 3 & 4); `dashboard` CLI (Task 5). Deferred Foundation `updated_at` onupdate closed (Task 1).
- **Placeholder scan:** none — repository/query/dashboard/CLI code is complete and no contradictory "write the clean version instead" note remains.
- **Type consistency:** `shortlist_rows(session) -> list[ShortlistRow]` and `pipeline_rows(session) -> list[PipelineRow]` (dataclasses with the exact fields the view reads); `save_application`/`get_application`/`application_for_job`/`applications_by_status`/`update_application_status`/`latest_resume_version`/`latest_rendered_resume_version` signatures match their call sites in `queries.py` and `app.py`. CLI test patches `cli.subprocess.run`; the command imports `os`/`subprocess` at module level. `ApplicationStatus`/`JobStatus` `.value` usage matches the str-enums.

---

## Notes to carry into later plans

- **LinkedIn scraper plan:** new scraped jobs land at `status=raw`; they flow through discovery → `shortlisted` and then appear on the Shortlist page automatically. No dashboard change needed.
- **v2 (memo):** Gmail auto-status could write `applications.status` directly via `update_application_status`; the board already renders it.
- A "render from the board" button should call `render.service.render_version(session, latest_resume_version(session, job_id).id, RenderConfig())` only after checking that `latest_resume_version(...)` is not `None`; wire it when the render flow is exercised end-to-end.

## Execution Handoff

After this plan is executed and green, the last v1 component is the **LinkedIn scraper** (see its plan), which requires a live-HTML calibration session.
