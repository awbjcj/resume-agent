# Board as the Single Board-Data Seam + Prune Use-Case (Candidates B + C + D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `services` the single place board-data *policy*, *assembled reads*, and the *prune use-case* live — collapse the hand-built `JobDetail` projection in the API router (B), stop the Streamlit dashboard from reaching past `board` into `tracking.repository` for mutations (C), and lift the duplicated prune override-merge into a `services.prune` use-case (D).

**Architecture:** `board` already wraps mutation policy (`set_stage`/`set_archived`/`delete`/`upsert_application`) and the board read-models. Two adapters bypass it: the API router assembles `JobDetail` by hand from four queries plus an 18-field manual projection, and the dashboard imports the repository's mutation functions directly. We add one deep read-model — `board.get_job_detail` returning a flat `JobDetailRow` the schema projects in one `model_validate` line — and route every dashboard mutation through `board`. Raw list projections (`shortlist_rows`/`pipeline_rows`/`triage_rows`) stay in `tracking.queries` and remain callable by both adapters: wrapping them in `board` would add shallow pass-throughs and would fight the dashboard's rich in-process filtering. Separately, prune is the one use-case all three adapters call `tracking` for directly, duplicating the config-load + sparse override-merge + preview/run dispatch (byte-identical between CLI and API); we lift that into `services.prune`. `match_gap` is deliberately untouched — it is already deep at `tracking.match_gap` and its per-adapter prep (canonicalizer, existence guards, formatting) is genuine divergence, not duplication.

**Tech Stack:** Python 3 / FastAPI / SQLModel / pydantic v2 (`from_attributes`); pytest. The `api → services → tracking` dependency points one way only — `services`/`tracking` never import `api`.

**Domain terms (CONTEXT.md):** *Board seam*, *JobDetailRow*.

---

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `src/resume_agent/tracking/queries.py` | `JobDetailRow` dataclass + `job_detail_row()` assembling it (reuses `_shortlist_row`) | Modify |
| `src/resume_agent/services/board.py` | `get_job_detail()` wraps `job_detail_row` (loads facts like `job_detail_facets`) | Modify |
| `src/resume_agent/api/routers/jobs.py` | Collapse `_job_detail` (32–75) to `board.get_job_detail` + `JobDetail.model_validate` | Modify |
| `src/resume_agent/dashboard/pages.py` | Mutations → `board.set_stage`/`set_archived`/`delete`/`upsert_application`; drop repository mutation imports | Modify |
| `tests/test_job_detail_row.py` | Unit test for the read-model assembly | Create |
| `tests/api/test_job_detail.py` | API test: detail shape unchanged through the new path | Extend |
| `tests/test_dashboard_seam.py` | Fitness test: dashboard imports no mutation funcs from `tracking.repository` | Create |
| `src/resume_agent/services/prune.py` | `prune()` use-case: load config, merge sparse overrides, dispatch preview/run | Create |
| `src/resume_agent/cli.py:445-482` · `api/routers/prune.py` · `dashboard/pages.py:744-773` | Call `services.prune`; drop the duplicated override-merge | Modify |
| `tests/test_services_prune.py` | Unit test for the prune use-case (override merge + dispatch) | Create |

---

### Task 1: `JobDetailRow` read-model + `job_detail_row`

**Files:**
- Modify: `src/resume_agent/tracking/queries.py` (add after `ShortlistRow`, ~line 60; and a builder near `job_facets`, ~line 199)
- Test: `tests/test_job_detail_row.py`

`JobDetailRow` is flat and field-named to match the `JobDetail` schema exactly (note `id`, not `job_id`), so `JobDetail.model_validate(row)` projects it in one line. The facet half reuses `_shortlist_row` (no re-derivation); the detail half adds the job's own columns plus sub-resources.

- [ ] **Step 1: Write the failing test**

```python
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.queries import job_detail_row
from resume_agent.tracking.repository import save_application
from resume_agent.tracking.tables import Application, Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_job_detail_row_assembles_facets_and_subresources():
    with _session() as session:
        job = Job(
            source="greenhouse", url="http://x", company="Acme", title="SWE",
            location="Remote", jd_text="build things", status=JobStatus.tailored.value,
            fit_score=88, fit_rationale="great",
            criteria_json={"remote_policy": "remote", "seniority": "senior"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        save_application(session, Application(job_id=job.id, status="applied"))

        row = job_detail_row(session, job.id)

    assert row.id == job.id
    assert row.source == "greenhouse"
    assert row.jd_text == "build things"
    assert row.status == JobStatus.tailored.value
    assert row.remote_policy == "remote"      # parsed from criteria_json by _shortlist_row
    assert row.seniority == "senior"
    assert row.has_progress is True           # tailored status
    assert row.application is not None and row.application.status == "applied"
    assert isinstance(row.resume_versions, list)
    assert isinstance(row.skills, list)


def test_job_detail_row_returns_none_for_missing_job():
    with _session() as session:
        assert job_detail_row(session, 9999) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_detail_row.py -v`
Expected: FAIL with `ImportError: cannot import name 'job_detail_row'`.

- [ ] **Step 3: Add `JobDetailRow` + `job_detail_row`**

In `src/resume_agent/tracking/queries.py`, add the dataclass after `ShortlistRow` (after line 60):

```python
@dataclass
class JobDetailRow:
    # Detail-only columns (named to match the JobDetail schema: id, not job_id)
    id: int
    source: str
    url: str | None
    jd_text: str
    status: str
    criteria_json: dict | None
    archived_at: datetime | None
    created_at: datetime
    has_progress: bool
    application: Application | None
    resume_versions: list
    # Facet half (mirrors ShortlistRow; reused via _shortlist_row)
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]
    sic_major: str | None = None
    sic_label: str | None = None
    sic_division: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
```

Add the builder near `job_facets` (after line 199):

```python
def job_detail_row(
    session: Session,
    job_id: int,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = "data/skill_aliases.json",
) -> "JobDetailRow | None":
    """Assemble the full detail read-model for one job.

    Reuses ``_shortlist_row`` for the facet half so ``covered`` and the parsed
    meta fields match the board card, then adds the detail-only columns and
    sub-resources. Returns ``None`` when the job does not exist.
    """
    job = session.get(Job, job_id)
    if job is None:
        return None
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    sic_table = sic_tax.load_sic_table()
    facets = _shortlist_row(job, tokens, aliases, sic_table)
    jid = _require_job_id(job)
    return JobDetailRow(
        id=jid,
        source=job.source,
        url=job.url,
        jd_text=job.jd_text,
        status=job.status,
        criteria_json=job.criteria_json,
        archived_at=job.archived_at,
        created_at=job.created_at,
        has_progress=has_progress(session, jid),
        application=application_for_job(session, jid),
        resume_versions=resume_versions_for_job(session, jid),
        company=facets.company,
        title=facets.title,
        location=facets.location,
        fit_score=facets.fit_score,
        fit_rationale=facets.fit_rationale,
        sponsorship_signal=facets.sponsorship_signal,
        salary_min=facets.salary_min,
        salary_max=facets.salary_max,
        salary_currency=facets.salary_currency,
        remote_policy=facets.remote_policy,
        seniority=facets.seniority,
        employment_type=facets.employment_type,
        industry=facets.industry,
        company_size=facets.company_size,
        posted_at=facets.posted_at,
        skills=facets.skills,
        sic_major=facets.sic_major,
        sic_label=facets.sic_label,
        sic_division=facets.sic_division,
        location_country=facets.location_country,
        location_region=facets.location_region,
        location_city=facets.location_city,
    )
```

Add `resume_versions_for_job` to the existing `from resume_agent.tracking.repository import (...)` block at the top of `queries.py` (it already imports `application_for_job`, `has_progress`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_detail_row.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/resume_agent/tracking/queries.py tests/test_job_detail_row.py
git add src/resume_agent/tracking/queries.py tests/test_job_detail_row.py
git commit -m "feat(queries): add JobDetailRow read-model for the detail view"
```

---

### Task 2: `board.get_job_detail` + collapse the router projection (B)

**Files:**
- Modify: `src/resume_agent/services/board.py`
- Modify: `src/resume_agent/api/routers/jobs.py:32-75,78-128`
- Test: `tests/api/test_job_detail.py`

- [ ] **Step 1: Write the failing API test**

```python
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.repository import save_application
from resume_agent.tracking.tables import Application, Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, **kw):
    with get_session(app.state.engine) as session:
        job = Job(source="manual", jd_text="jd body", **kw)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_job_detail_returns_full_shape():
    client = _client()
    with client:
        jid = _seed(
            client.app, company="Acme", title="SWE", status=JobStatus.tailored.value,
            fit_score=77, criteria_json={"remote_policy": "remote"},
        )
        with get_session(client.app.state.engine) as session:
            save_application(session, Application(job_id=jid, status="submitted", notes="ref"))
        resp = client.get(f"/api/jobs/{jid}")
        body = resp.json()
    assert resp.status_code == 200
    assert body["id"] == jid
    assert body["jdText"] == "jd body"
    assert body["remotePolicy"] == "remote"
    assert body["hasProgress"] is True
    assert body["application"]["status"] == "submitted"
    assert body["application"]["notes"] == "ref"
    assert body["resumeVersions"] == []
    assert "skills" in body


def test_job_detail_404_for_missing():
    client = _client()
    with client:
        resp = client.get("/api/jobs/9999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it passes against the OLD router, then we refactor without breaking it**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_detail.py -v`
Expected: PASS (the old `_job_detail` already returns this shape). This test is the safety net for the refactor.

- [ ] **Step 3: Add `board.get_job_detail`**

In `src/resume_agent/services/board.py`, add after `job_detail_facets` (line 69), and add `job_detail_row` to the `from resume_agent.tracking.queries import (...)` block:

```python
def get_job_detail(
    session: Session, job_id: int, *, facts_path: str = DEFAULT_FACTS
):
    """Full detail read-model for one job (the API detail endpoint).

    Loads facts the same way the board list does so ``covered`` is consistent
    between card and detail.
    """
    facts = load_facts(facts_path) if Path(facts_path).exists() else None
    return job_detail_row(session, job_id, facts=facts)
```

- [ ] **Step 4: Collapse the router**

In `src/resume_agent/api/routers/jobs.py`, replace `_job_detail` (lines 32–75) with a thin response helper, and update the imports (drop `application_for_job`, `resume_versions_for_job`, the per-field schema imports that are no longer hand-used; keep `get_job` for the mutation guards):

```python
def _job_detail_response(session: Session, job_id: int) -> JobDetail:
    row = board.get_job_detail(session, job_id)
    if row is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return JobDetail.model_validate(row)
```

Then point `get_job_detail`, `patch_job`, and `create_manual_job` at it:

```python
@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(job_id: int, session: Session = Depends(get_session)):
    return _job_detail_response(session, job_id)
```

In `patch_job` replace the trailing `return _job_detail(session, job_id)` with `return _job_detail_response(session, job_id)`. In `create_manual_job` replace `return _job_detail(session, job.id)` with `return _job_detail_response(session, job.id)`.

- [ ] **Step 5: Run the API tests + contract gate**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_detail.py tests/api/test_openapi_contract.py -v`
Expected: PASS. The `JobDetail` schema is unchanged, so OpenAPI does not drift.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/resume_agent/services/board.py src/resume_agent/api/routers/jobs.py
git add src/resume_agent/services/board.py src/resume_agent/api/routers/jobs.py tests/api/test_job_detail.py
git commit -m "refactor(api): project JobDetail via board.get_job_detail in one model_validate"
```

---

### Task 3: Route dashboard mutations through `board` (C)

**Files:**
- Modify: `src/resume_agent/dashboard/pages.py:49-60,313-322,430-435,452-460,663,718,725,739`
- Test: `tests/test_dashboard_seam.py`

All seven mutation sites already have their policy wrapper in `board`. Delete is already UI-gated on `has_progress` (`row.has_progress` at 464, `all_deletable(...)` at 730), so routing it through `board.delete` is behavior-preserving.

- [ ] **Step 1: Write the failing fitness test**

```python
from resume_agent.dashboard import pages

# `from tracking.repository import save_job` would bind pages.save_job; after the
# refactor the dashboard owns no mutation policy, so none of these may be present.
FORBIDDEN = [
    "save_job", "archive_job", "restore_job", "delete_job",
    "save_application", "update_application_status",
]


def test_dashboard_holds_no_repository_mutations():
    leaked = [name for name in FORBIDDEN if hasattr(pages, name)]
    assert leaked == [], f"dashboard bypasses the board seam: {leaked}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_seam.py -v`
Expected: FAIL — all six names currently leak.

- [ ] **Step 3: Replace the mutation sites with `board` calls**

Add `from resume_agent.services import board` to `pages.py` imports. Then:

Approve button (313–322):

```python
                if st.button("Approve for tailoring  →", key=f"approve-{row.job_id}"):
                    if board.set_stage(session, row.job_id, JobStatus.approved.value) is None:
                        st.error(f"Job #{row.job_id} no longer exists.")
                        st.rerun()
                        return
                    st.success(f"Approved {row.title or 'job'} #{row.job_id}.")
                    st.rerun()
```

Application upsert (the `if application is None: save_application(...) else update_application_status(...)` branch around 428–435):

```python
                    board.upsert_application(session, row.job_id, status=new_status, notes=notes or None)
```

Set-stage (452–457):

```python
            if st.button("Set stage", key=f"setstage-{row.job_id}"):
                if board.set_stage(session, row.job_id, new_stage) is not None:
                    st.rerun()
```

Archive single (460) → `board.set_archived(session, row.job_id, True)`.
Restore single (663) and bulk (718) → `board.set_archived(session, jid, False)`.
Archive bulk (725) → `board.set_archived(session, jid, True)`.
Delete bulk (739) → `board.delete(session, jid)`.

- [ ] **Step 4: Drop the now-dead imports + helpers**

Remove `save_job`, `archive_job`, `restore_job`, `delete_job`, `save_application`, `update_application_status` from the `from resume_agent.tracking.repository import (...)` block (49–60). Keep `application_for_job`, `get_job`, `prune_preview`, `prune_run` (still used for reads/Candidate D). If `_new_application` and the `Application` import are now unused, delete them. Let `ruff` confirm.

- [ ] **Step 5: Run the fitness test, dashboard tests, and lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_seam.py tests/test_dashboard_app.py tests/test_cli_dashboard.py -v`
Expected: PASS (fitness test green; existing dashboard tests unchanged — behavior preserved).

Run: `ruff check src/resume_agent/dashboard/pages.py`
Expected: no errors (catches any leftover unused import).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/dashboard/pages.py tests/test_dashboard_seam.py
git commit -m "refactor(dashboard): route mutations through the board seam"
```

---

### Task 4: Lift prune into a `services.prune` use-case (D)

**Files:**
- Create: `src/resume_agent/services/prune.py`
- Modify: `src/resume_agent/cli.py:453-482`
- Modify: `src/resume_agent/api/routers/prune.py`
- Modify: `src/resume_agent/dashboard/pages.py:744-773`
- Test: `tests/test_services_prune.py`

The config-load + sparse override-merge + preview/run dispatch is duplicated across all three adapters (byte-identical between CLI and API). One use-case owns it. The dashboard still calls `load_prune_config` for one thing only — seeding its number-input defaults — which is a pure read, not the duplicated logic.

- [ ] **Step 1: Write the failing test**

```python
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services.prune import prune
from resume_agent.tracking.tables import Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_prune_dry_run_counts_without_writing(tmp_path):
    cfg = tmp_path / "prune.yaml"
    cfg.write_text("fit_threshold: 40\nstale_days: 30\nretention_days: 90\n", encoding="utf-8")
    with _session() as session:
        session.add(Job(source="manual", jd_text="x", status=JobStatus.rejected.value))
        session.commit()
        report = prune(session, dry_run=True, config_path=str(cfg))
        # dry run writes nothing
        remaining = session.exec(__import__("sqlmodel").select(Job)).all()
    assert report.archived >= 1
    assert all(j.archived_at is None for j in remaining)


def test_prune_override_beats_config(tmp_path):
    cfg = tmp_path / "prune.yaml"
    cfg.write_text("fit_threshold: 40\nstale_days: 30\nretention_days: 90\n", encoding="utf-8")
    with _session() as session:
        # fit 50 survives the file's threshold (40) but not an override of 60
        session.add(Job(source="manual", jd_text="x", status=JobStatus.shortlisted.value, fit_score=50))
        session.commit()
        low = prune(session, dry_run=True, fit_threshold=60, config_path=str(cfg))
        base = prune(session, dry_run=True, config_path=str(cfg))
    assert low.low_fit == 1
    assert base.low_fit == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_prune.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.services.prune'`.

- [ ] **Step 3: Write the use-case**

```python
"""Prune use-case: load config, apply sparse overrides, dispatch preview/run."""

from __future__ import annotations

from sqlmodel import Session

from resume_agent.tracking.prune import PruneReport
from resume_agent.tracking.prune_config import load_prune_config
from resume_agent.tracking.repository import prune_preview, prune_run

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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_prune.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Point the CLI at the use-case**

In `src/resume_agent/cli.py`, replace the body of the prune command (453–482) — the `load_prune_config` + override-dict + `model_copy` + `prune_preview`/`prune_run` block — with:

```python
    with get_session(_engine(db_url)) as session:
        report = run_prune(
            session, dry_run=dry_run, fit_threshold=fit,
            stale_days=stale_days, retention_days=retention_days, config_path=config,
        )
    if dry_run:
        typer.echo(
            f"[dry-run] {report.rejected} rejected, {report.low_fit} low-fit, "
            f"{report.stale} stale -> {report.archived} to archive; "
            f"{report.expired} to expire, {report.skipped} skipped (have progress)"
        )
    else:
        typer.echo(
            f"+{report.archived} archived "
            f"({report.rejected} rejected, {report.low_fit} low-fit, {report.stale} stale), "
            f"{report.expired} expired, {report.skipped} skipped"
        )
```

Update the CLI imports: add `from resume_agent.services.prune import prune as run_prune`; remove `load_prune_config` and `prune_preview`/`prune_run` from their import lines if no longer used elsewhere in `cli.py` (let `ruff` confirm). The alias is required because the Typer command function is already named `prune`.

- [ ] **Step 6: Point the API at the use-case**

Replace the body of `src/resume_agent/api/routers/prune.py`'s `prune` endpoint (the `load_prune_config` + override-dict + dispatch, lines 19–29) with:

```python
@router.post("/prune", response_model=PruneReportOut)
def prune_endpoint(body: PruneOverrides, session: Session = Depends(get_session)):
    report = prune(
        session, dry_run=body.dry_run, fit_threshold=body.fit_threshold,
        stale_days=body.stale_days, retention_days=body.retention_days,
    )
    return PruneReportOut.model_validate(report)
```

Update imports: add `from resume_agent.services.prune import prune`; drop `load_prune_config`, `prune_preview`, `prune_run`. (Rename the handler to `prune_endpoint` so it does not shadow the imported `prune`.)

- [ ] **Step 7: Point the dashboard at the use-case (keep config load for widget defaults)**

In `src/resume_agent/dashboard/pages.py`, `_render_prune_panel` keeps `config = load_prune_config(_PRUNE_CONFIG_PATH)` to seed the inputs, but the preview/run calls go through the use-case:

```python
def _render_prune_panel(session) -> None:
    config = load_prune_config(_PRUNE_CONFIG_PATH)  # defaults for the widgets only
    with st.expander("Prune (archive junk, expire old)"):
        c1, c2, c3 = st.columns(3)
        fit = c1.number_input("Fit below", 0, 100, config.fit_threshold, key="prune_fit")
        stale = c2.number_input("Stale days", 0, 3650, config.stale_days, key="prune_stale")
        retain = c3.number_input("Retention days", 0, 3650, config.retention_days, key="prune_retain")
        preview = prune(session, dry_run=True, fit_threshold=fit, stale_days=stale, retention_days=retain)
        st.caption(
            f"{preview.rejected} rejected · {preview.low_fit} low-fit · {preview.stale} stale "
            f"→ {preview.archived} archive · {preview.expired} expire · "
            f"{preview.skipped} skipped (have progress)"
        )
        if st.button("Prune now", key="prune_now"):
            _confirm_prune(session, fit, stale, retain)


@st.dialog("Run prune")
def _confirm_prune(session, fit: int, stale: int, retain: int) -> None:
    report = prune(session, dry_run=True, fit_threshold=fit, stale_days=stale, retention_days=retain)
    st.write(
        f"Archive {report.archived} job(s) and permanently delete {report.expired} "
        "expired archived job(s)? Expiry cannot be undone."
    )
    if st.button("Confirm prune", key="confirm_prune"):
        prune(session, dry_run=False, fit_threshold=fit, stale_days=stale, retention_days=retain)
        st.rerun()
```

Add `from resume_agent.services.prune import prune` to the imports; remove `prune_preview` and `prune_run` from the `tracking.repository` import block. Keep `load_prune_config`.

- [ ] **Step 8: Run prune tests across all three adapters + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_prune.py tests/test_cli_prune.py tests/api/test_prune_render.py -v`
Expected: PASS (adapter behavior preserved — same report text/shape).

Run: `ruff check src/resume_agent/services/prune.py src/resume_agent/cli.py src/resume_agent/api/routers/prune.py src/resume_agent/dashboard/pages.py`
Expected: no errors (catches any leftover unused import).

- [ ] **Step 9: Commit**

```bash
git add src/resume_agent/services/prune.py src/resume_agent/cli.py src/resume_agent/api/routers/prune.py src/resume_agent/dashboard/pages.py tests/test_services_prune.py
git commit -m "refactor(prune): lift config override-merge into services.prune use-case"
```

---

### Task 5: Full-suite verification

- [ ] **Step 1: Run the whole suite + lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: all green.

- [ ] **Step 2: Regenerate the TS client if anything in OpenAPI moved (it should not have)**

Run: `bash scripts/gen_ts_client.sh` then `git status contracts/`
Expected: no diff — `JobDetail` is unchanged. If a diff appears, the refactor altered the wire contract; investigate before committing.

---

## Self-Review

- **Spec coverage:** B (collapse JobDetail projection) → Tasks 1–2 ✓; C (dashboard mutations through board) → Task 3 ✓; D (prune override-merge into `services.prune`) → Task 4 ✓; read scope decision (mutations + detail only; raw projections stay in queries) → honoured (no `board` read wrappers added; `shortlist_rows`/`pipeline_rows`/`triage_rows` untouched) ✓; layering rule (services/tracking never import api) → honoured: `JobDetailRow` lives in `tracking`, schema does the projection; `services.prune` imports only `tracking` ✓; `match_gap` left alone (already deep) ✓.
- **Placeholder scan:** Task 3 Step 3 lists single-line replacements per site rather than re-pasting each surrounding block — the exact line anchors and the target `board` call are given, and the sites are near-identical one-liners. All multi-line code (Tasks 1, 2, fitness test) is complete.
- **Type consistency:** `job_detail_row` (Task 1) is referenced by `board.get_job_detail` (Task 2); `JobDetailRow` field names match the `JobDetail` schema fields one-to-one (verified against `api/schemas/jobs.py:93-128`); `board.set_stage`/`set_archived`/`delete`/`upsert_application` signatures match `services/board.py:111-135`.

---

## Notes

- `board.get_job_detail` re-loads facts per call (mirrors `job_detail_facets`). Fine for a single-row detail endpoint; do not pre-optimise.
- `services.prune` re-loads the prune YAML on each call, so the dashboard's live preview re-reads it per keystroke. Negligible for a small local file; do not pre-optimise.
- `match_gap` is intentionally not wrapped — it is already deep at `tracking.match_gap`; a service pass-through there would fail the deletion test.
