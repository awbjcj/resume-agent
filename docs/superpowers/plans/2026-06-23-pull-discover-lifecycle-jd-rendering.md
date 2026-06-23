# Pull/Discover Lifecycle + JD Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make discover incremental and idempotent, replace the broken re-extract/re-score modes with a scoped `reprocess`, add a one-button `refresh`, harden dedup, render job descriptions as formatted markdown, and rename "Best-have" → "Nice-to-have".

**Architecture:** Backend is a layered Python app (SQLModel + FastAPI + Typer CLI) where `services/` is the use-case seam over `discovery/pipeline.py` and `discovery/ingest.py`. Schema changes use idempotent `ensure_*_column` migrations run from `init_db`. The web SPA (`web/`, Vite + React + shadcn) talks to the API via a generated typed client; long ops are Runs with SSE. We add two nullable `Job` columns, a pure `reprocess` funnel over a job scope, a content-fingerprint dedup fallback, a `markdownify`-based ingest path, and a `react-markdown` renderer.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy, FastAPI, Typer, pytest; React 19, TypeScript, Vitest, `react-markdown`, `markdownify`.

**Test commands:**
- Backend (offline): `.venv/Scripts/python.exe -m pytest`
- Backend lint: `ruff check`
- Web: `cd web && npm run test` (vitest)
- OpenAPI regen: `bash scripts/gen_ts_client.sh`

---

## File-structure map

**Create:**
- `tests/test_migrate_lifecycle.py` — migration backfill tests
- `web/src/lib/format/prettify.ts` — `prettifyPlainText()` for legacy flat JD text
- `web/src/lib/format/prettify.test.ts` — vitest for the above

**Modify (backend):**
- `src/resume_agent/tracking/dedup.py` — title abbreviations + `compute_content_fingerprint`
- `src/resume_agent/tracking/tables.py` — two new `Job` columns
- `src/resume_agent/tracking/migrate.py` — two new `ensure_*_column` helpers
- `src/resume_agent/db.py` — wire the new migrations
- `src/resume_agent/tracking/repository.py` — `find_existing` fingerprint fallback
- `src/resume_agent/discovery/merge.py` — carry `content_fingerprint` in IncomingJob + text updates
- `src/resume_agent/discovery/ingest.py` — pass fingerprint through `save_or_upgrade`
- `src/resume_agent/discovery/pipeline.py` — `reject_category` writes; new `reprocess`; delete `reextract`/`backfill_rescore`
- `src/resume_agent/services/discovery.py` — `reprocess_jobs`, `refresh_jobs`; delete `reextract_metadata`/`rescore_existing`
- `src/resume_agent/cli.py` — drop `--reextract`/`--rescore`; add `reprocess` + `refresh` commands
- `src/resume_agent/api/schemas/runs.py` — `ReprocessParams`, `RefreshParams`; trim `DiscoverParams`
- `src/resume_agent/api/routers/runs.py` — trim discover dispatch; add `/reprocess`, `/refresh`
- `src/resume_agent/discovery/connectors/text.py` — `html_to_markdown`
- connectors: `greenhouse.py`, `lever.py`, `ashby.py`, `google.py`, `remoteok.py`, `tesla.py`, `workday.py`, `adzuna.py` — switch HTML payloads to `html_to_markdown`
- `pyproject.toml` — add `markdownify`

**Modify (web):**
- `web/package.json` — add `react-markdown`
- `web/src/components/JobModal.tsx` — markdown render
- `web/src/components/SkillMatrix.tsx` — "Nice-to-have" label + comment
- `web/src/components/JobCard.tsx` — comment rename
- `web/src/features/runs/use-launch-run.ts` — launchers for reprocess/refresh, drop modes
- `web/src/features/runs/RunLaunchDialogs.tsx` — simplify Discover, add Reprocess + Refresh
- `web/src/features/runs/RunActions.tsx` — wire new actions

**Test files touched:** `tests/test_discovery_ingest.py`, `tests/test_discovery_pipeline.py`, `tests/test_cli_discovery.py`, `tests/api/test_runs.py` (or nearest), `tests/api/test_openapi_contract.py` (regenerated), `web/src/components/SkillMatrix.test.tsx` (if present) + new vitest files.

---

## Task 1: Title abbreviation normalization (dedup)

**Files:**
- Modify: `src/resume_agent/tracking/dedup.py`
- Test: `tests/test_tracking_dedup.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_tracking_dedup.py`:

```python
from resume_agent.tracking.dedup import compute_dedup_key


def test_abbreviated_titles_collapse_to_same_key():
    assert compute_dedup_key("Acme", "Sr SWE") == compute_dedup_key("Acme", "Software Engineer")
    assert compute_dedup_key("Acme", "Backend Eng") == compute_dedup_key("Acme", "Backend Engineer")


def test_distinct_roles_stay_distinct():
    assert compute_dedup_key("Acme", "Data Scientist") != compute_dedup_key("Acme", "Software Engineer")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_dedup.py -v`
Expected: FAIL — "Sr SWE" normalizes to `swe`, not `software engineer`.

- [ ] **Step 3: Implement abbreviation expansion**

In `src/resume_agent/tracking/dedup.py`, add the map and apply it inside `_normalize_title`:

```python
# Conservative role-noun abbreviations expanded so cross-source title variants
# collapse to one key. Seniority words are already stripped by _SENIORITY, so
# only role nouns belong here. Keep this small to avoid over-collapsing.
_ABBREVIATIONS = {
    "swe": "software engineer",
    "sde": "software engineer",
    "eng": "engineer",
    "engr": "engineer",
    "dev": "developer",
    "mgr": "manager",
}


def _expand_abbreviations(normalized: str) -> str:
    return " ".join(_ABBREVIATIONS.get(token, token) for token in normalized.split())


def _normalize_title(title: str) -> str:
    return _expand_abbreviations(_normalize(_SENIORITY.sub("", title.strip())))
```

(Replace the existing `_normalize_title`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_dedup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/dedup.py tests/test_tracking_dedup.py
git commit -m "feat(dedup): expand role-noun abbreviations in title normalization"
```

---

## Task 2: Content fingerprint helper (dedup)

**Files:**
- Modify: `src/resume_agent/tracking/dedup.py`
- Test: `tests/test_tracking_dedup.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracking_dedup.py`:

```python
from resume_agent.tracking.dedup import compute_content_fingerprint


def test_fingerprint_ignores_whitespace_and_case():
    a = compute_content_fingerprint("Build  great\nSystems")
    b = compute_content_fingerprint("build great systems")
    assert a is not None and a == b


def test_fingerprint_differs_for_different_text():
    assert compute_content_fingerprint("alpha role") != compute_content_fingerprint("beta role")


def test_fingerprint_none_for_blank():
    assert compute_content_fingerprint("   ") is None
    assert compute_content_fingerprint(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_dedup.py -k fingerprint -v`
Expected: FAIL — `compute_content_fingerprint` undefined.

- [ ] **Step 3: Implement the fingerprint**

In `src/resume_agent/tracking/dedup.py`, add at top `import hashlib` (keep existing `import re`) and:

```python
_WHITESPACE = re.compile(r"\s+")


def compute_content_fingerprint(jd_text: str | None) -> str | None:
    """A whitespace/case-insensitive hash of a JD, used as a keyless dedup fallback."""
    if not jd_text or not jd_text.strip():
        return None
    normalized = _WHITESPACE.sub(" ", jd_text.lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_dedup.py -k fingerprint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/dedup.py tests/test_tracking_dedup.py
git commit -m "feat(dedup): add content fingerprint helper for keyless dedup"
```

---

## Task 3: Schema columns + migrations

**Files:**
- Modify: `src/resume_agent/tracking/tables.py:52` (Job model)
- Modify: `src/resume_agent/tracking/migrate.py`
- Modify: `src/resume_agent/db.py:49-53`
- Test: `tests/test_migrate_lifecycle.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_lifecycle.py`:

```python
from sqlalchemy import text

from resume_agent.db import make_engine
from resume_agent.tracking.migrate import (
    ensure_content_fingerprint_column,
    ensure_reject_category_column,
)


def _legacy_engine():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE jobs (id INTEGER PRIMARY KEY, reject_reason VARCHAR, "
                "dedup_key VARCHAR, jd_text VARCHAR)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO jobs (id, reject_reason, dedup_key, jd_text) VALUES "
                "(1, 'off-target role: trucking', NULL, 'jd one'), "
                "(2, 'salary below minimum', 'acme|eng', 'jd two'), "
                "(3, NULL, NULL, 'jd three')"
            )
        )
    return engine


def test_reject_category_backfills_from_reason():
    engine = _legacy_engine()
    ensure_reject_category_column(engine)
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, reject_category FROM jobs")).fetchall())
    assert rows[1] == "relevance"
    assert rows[2] == "filtered"
    assert rows[3] is None


def test_content_fingerprint_backfills_all_rows():
    engine = _legacy_engine()
    ensure_content_fingerprint_column(engine)
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, content_fingerprint FROM jobs")).fetchall())
    assert all(rows[i] for i in (1, 2, 3))  # every non-blank jd_text got a fingerprint
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_lifecycle.py -v`
Expected: FAIL — the `ensure_*` functions don't exist.

- [ ] **Step 3: Add the columns to the model**

In `src/resume_agent/tracking/tables.py`, in `class Job`, replace the `reject_reason` line with:

```python
    reject_reason: str | None = None
    reject_category: str | None = None
    content_fingerprint: str | None = Field(default=None, index=True)
```

- [ ] **Step 4: Add the migrations**

In `src/resume_agent/tracking/migrate.py`, update the import and append two helpers:

```python
from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key
```

```python
def ensure_reject_category_column(engine: Engine) -> None:
    """Idempotently add ``jobs.reject_category`` and classify existing reject reasons."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "reject_category" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN reject_category VARCHAR"))
        rows = conn.execute(
            text(
                "SELECT id, reject_reason FROM jobs "
                "WHERE reject_reason IS NOT NULL AND reject_category IS NULL"
            )
        ).fetchall()
        for row_id, reason in rows:
            category = "relevance" if str(reason).startswith("off-target role") else "filtered"
            conn.execute(
                text("UPDATE jobs SET reject_category = :c WHERE id = :i"),
                {"c": category, "i": row_id},
            )


def ensure_content_fingerprint_column(engine: Engine) -> None:
    """Idempotently add ``jobs.content_fingerprint`` and backfill it for every row."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "content_fingerprint" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN content_fingerprint VARCHAR"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_content_fingerprint "
                "ON jobs (content_fingerprint)"
            )
        )
        rows = conn.execute(
            text("SELECT id, jd_text FROM jobs WHERE content_fingerprint IS NULL")
        ).fetchall()
        for row_id, jd_text in rows:
            fingerprint = compute_content_fingerprint(jd_text)
            if fingerprint:
                conn.execute(
                    text("UPDATE jobs SET content_fingerprint = :f WHERE id = :i"),
                    {"f": fingerprint, "i": row_id},
                )
```

- [ ] **Step 5: Wire the migrations into init_db**

In `src/resume_agent/db.py`, update the import block and `init_db`:

```python
from resume_agent.tracking.migrate import (
    ensure_archived_at_column,
    ensure_content_fingerprint_column,
    ensure_dedup_key_column,
    ensure_posted_at_column,
    ensure_reject_category_column,
)
```

```python
def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_dedup_key_column(engine)
    ensure_posted_at_column(engine)
    ensure_archived_at_column(engine)
    ensure_reject_category_column(engine)
    ensure_content_fingerprint_column(engine)
```

- [ ] **Step 6: Run tests + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_lifecycle.py -v && ruff check`
Expected: PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/tracking/tables.py src/resume_agent/tracking/migrate.py src/resume_agent/db.py tests/test_migrate_lifecycle.py
git commit -m "feat(schema): add reject_category + content_fingerprint columns with backfill"
```

---

## Task 4: Ingest fingerprint fallback

**Files:**
- Modify: `src/resume_agent/discovery/merge.py:61-64,127-136`
- Modify: `src/resume_agent/discovery/ingest.py:57,71-82`
- Modify: `src/resume_agent/tracking/repository.py:49-63`
- Test: `tests/test_discovery_ingest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discovery_ingest.py` (it already has a `_session()` helper / `add_job` import — reuse them; if it builds sessions inline, mirror that pattern):

```python
def test_keyless_near_duplicate_collapses_via_fingerprint():
    from resume_agent.discovery.ingest import add_job
    from resume_agent.tracking.repository import jobs_by_status
    from resume_agent.tracking.tables import JobStatus

    with _session() as s:  # use the file's existing session helper
        first = add_job(s, source="remoteok", jd_text="Build great systems for us")
        second = add_job(s, source="remoteok", jd_text="Build  great   systems for us")
        assert first is not None
        assert second is None  # deduped by fingerprint, not inserted
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1
```

> If `tests/test_discovery_ingest.py` has no `_session()` helper, copy the in-memory
> session setup from `tests/test_discovery_pipeline.py` lines 24-27 into a local helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_ingest.py -k fingerprint -v`
Expected: FAIL — the second keyless job is inserted as a new row (count == 2).

- [ ] **Step 3: Carry the fingerprint on IncomingJob**

In `src/resume_agent/discovery/merge.py`, update the import and add a property next to `dedup_key`:

```python
from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key
```

```python
    @property
    def content_fingerprint(self) -> str | None:
        return compute_content_fingerprint(self.jd_text)
```

In `decide()`, every place that writes `updates["jd_text"] = incoming.jd_text` (the `RefreshText` branch ~line 127 and the `Rebase` branch ~line 150), add immediately after it:

```python
        updates["content_fingerprint"] = incoming.content_fingerprint
```

- [ ] **Step 4: Add the fingerprint fallback to find_existing**

In `src/resume_agent/tracking/repository.py`, replace `find_existing`:

```python
def find_existing(
    session: Session,
    url: str | None,
    jd_text: str,
    dedup_key: str | None = None,
    content_fingerprint: str | None = None,
) -> Job | None:
    """Match for dedupe: URL, then identical JD, then dedup_key, then (keyless) fingerprint."""
    if url:
        by_url = session.exec(select(Job).where(Job.url == url)).first()
        if by_url is not None:
            return by_url
    if jd_text:
        by_jd = session.exec(select(Job).where(Job.jd_text == jd_text)).first()
        if by_jd is not None:
            return by_jd
    if dedup_key:
        by_key = session.exec(select(Job).where(Job.dedup_key == dedup_key)).first()
        if by_key is not None:
            return by_key
    if dedup_key is None and content_fingerprint:
        return session.exec(
            select(Job).where(Job.content_fingerprint == content_fingerprint)
        ).first()
    return None
```

- [ ] **Step 5: Pass the fingerprint through ingest + set it on insert**

In `src/resume_agent/discovery/ingest.py`, in `save_or_upgrade` update the `find_existing` call:

```python
    existing = find_existing(
        session,
        incoming.url,
        incoming.jd_text,
        incoming.dedup_key,
        incoming.content_fingerprint,
    )
```

In `_apply`, in the `Insert` branch, add `content_fingerprint` to the `Job(...)` constructor:

```python
            dedup_key=incoming.dedup_key,
            content_fingerprint=incoming.content_fingerprint,
            status=JobStatus.raw.value,
```

- [ ] **Step 6: Reconcile the existing keyless test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_ingest.py -k "keeps_distinct_when_company_or_title_missing" -v`
Expected: PASS (that test uses *different* JD text, so fingerprints differ → still distinct). If it happens to use identical text, change one job's `jd_text` so the two remain genuinely different postings.

- [ ] **Step 7: Run the full ingest suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_ingest.py -v && ruff check`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/discovery/merge.py src/resume_agent/discovery/ingest.py src/resume_agent/tracking/repository.py tests/test_discovery_ingest.py
git commit -m "feat(dedup): collapse keyless near-duplicates via content fingerprint"
```

---

## Task 5: Classify rejections in the pipeline

**Files:**
- Modify: `src/resume_agent/discovery/pipeline.py:57-67` (run_filter), `139-177` (run_relevance)
- Test: `tests/test_discovery_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discovery_pipeline.py`:

```python
def test_filter_and_relevance_set_reject_category():
    cfg = SearchConfig(sponsorship_required=True, target_role="AI engineering roles")
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="bad role, nosponsor here", title="AI Engineer")
        add_job(s, source="manual", jd_text="drive a truck", title="CDL Driver")
        discover(s, cfg, facts, _ExtractAgent(), _FitAgent(), _Judge())
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        categories = {j.reject_category for j in rejected}
        assert categories == {"filtered", "relevance"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -k reject_category -v`
Expected: FAIL — `reject_category` is `None`.

- [ ] **Step 3: Set the category in run_filter**

In `src/resume_agent/discovery/pipeline.py` `run_filter`, in the `else` branch:

```python
        else:
            job.status = JobStatus.rejected.value
            job.reject_reason = decision.reject_reason
            job.reject_category = "filtered"
```

- [ ] **Step 4: Set the category in run_relevance**

In `run_relevance`, where it rejects:

```python
        if not verdict.keep:
            reason = (verdict.reason or "model rejected").strip()
            job.status = JobStatus.rejected.value
            job.reject_reason = f"off-target role: {reason}"
            job.reject_category = "relevance"
            session.add(job)
            rejected += 1
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "feat(pipeline): tag rejections with reject_category (filtered|relevance)"
```

---

## Task 6: The `reprocess` funnel

**Files:**
- Modify: `src/resume_agent/discovery/pipeline.py` (add `reprocess`, delete `reextract` + `backfill_rescore`)
- Test: `tests/test_discovery_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discovery_pipeline.py`:

```python
def test_reprocess_shortlisted_rescores_and_skips_progress():
    cfg = SearchConfig()  # no relevance target -> relevance gate is a no-op
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd a", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=10, criteria_json={}))
        save_job(s, Job(source="x", jd_text="jd b", title="Eng",
                        status=JobStatus.tailored.value, fit_score=10, criteria_json={}))

        counts = reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["shortlisted"])

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        tailored = jobs_by_status(s, JobStatus.tailored.value)
        assert shortlisted[0].fit_score == 90       # re-scored
        assert tailored[0].fit_score == 10           # progress-guarded, untouched
        assert counts[JobStatus.shortlisted.value] == 1


def test_reprocess_rejected_relevance_only():
    cfg = SearchConfig()
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(s, Job(source="x", jd_text="jd r", title="Eng",
                        status=JobStatus.rejected.value, reject_category="relevance"))
        save_job(s, Job(source="x", jd_text="jd f", title="Eng",
                        status=JobStatus.rejected.value, reject_category="filtered"))

        reprocess(s, cfg, facts, _ExtractAgent(), _FitAgent(), ["rejected:relevance"])

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        assert len(shortlisted) == 1                  # the relevance reject got a second chance
        assert {j.reject_category for j in rejected} == {"filtered"}  # filtered one untouched


def test_reprocess_unknown_scope_raises():
    import pytest
    with _session() as s:
        with pytest.raises(ValueError):
            reprocess(s, SearchConfig(), ProfileFacts(contact=Contact(name="Ada")),
                      _ExtractAgent(), _FitAgent(), ["bogus"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -k reprocess -v`
Expected: FAIL — `reprocess` undefined.

- [ ] **Step 3: Implement `reprocess` and delete the dead backfills**

In `src/resume_agent/discovery/pipeline.py`:

1. Update imports to add `has_progress`:

```python
from resume_agent.tracking.repository import has_progress, jobs_by_status, status_counts
```

2. **Delete** the `reextract` function (lines ~180-195) and the `backfill_rescore` function (lines ~218-244), and the now-unused `_REEXTRACT_STATUSES` constant (lines ~24-32).

3. Add scope selection + `reprocess`:

```python
_REPROCESS_ALL_STATUSES = (
    JobStatus.raw.value,
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
    JobStatus.shortlisted.value,
)


def _scope_jobs(session: Session, scope: str) -> list[Job]:
    if scope == "shortlisted":
        return jobs_by_status(session, JobStatus.shortlisted.value)
    if scope == "rejected:relevance":
        return [
            j for j in jobs_by_status(session, JobStatus.rejected.value)
            if j.reject_category == "relevance"
        ]
    if scope == "rejected:filtered":
        return [
            j for j in jobs_by_status(session, JobStatus.rejected.value)
            if j.reject_category == "filtered"
        ]
    if scope == "all":
        jobs: list[Job] = []
        for status in _REPROCESS_ALL_STATUSES:
            jobs.extend(jobs_by_status(session, status))
        return jobs
    raise ValueError(f"unknown reprocess scope: {scope}")


def reprocess(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
    scopes: list[str],
    relevance_agent: Runner | None = None,
    canonicalizer: Canonicalizer | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Reset in-scope, non-progressed jobs to raw and re-run the full funnel over them."""
    selected: dict[int, Job] = {}
    for scope in scopes:
        for job in _scope_jobs(session, scope):
            if job.id is None or job.id in selected:
                continue
            if has_progress(session, job.id):
                continue
            selected[job.id] = job
    for job in selected.values():
        job.status = JobStatus.raw.value
        job.reject_reason = None
        job.reject_category = None
        session.add(job)
    session.commit()
    return discover(
        session, config, profile_facts, extract_agent, fit_agent, relevance_agent,
        canonicalizer=canonicalizer, reporter=reporter,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v`
Expected: PASS. The old `test_reextract_*` and `test_backfill_rescore_*` tests will now fail to import — **delete those test functions** (in `tests/test_discovery_pipeline.py`: `test_reextract_rewrites_criteria_without_changing_status`, `test_backfill_rescore_populates_without_changing_fit_or_status`) and remove `backfill_rescore, reextract` from the file's imports (line 4-10), keeping `discover, run_relevance, run_score` and adding `reprocess`.

- [ ] **Step 5: Re-run + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v && ruff check src/resume_agent/discovery/pipeline.py`
Expected: PASS, no unused-import warnings.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "feat(pipeline): add scoped reprocess; remove dead reextract/backfill_rescore"
```

---

## Task 7: Service wrappers — reprocess_jobs + refresh_jobs

**Files:**
- Modify: `src/resume_agent/services/discovery.py` (delete `reextract_metadata`/`rescore_existing`; add `reprocess_jobs`, `refresh_jobs`, `RefreshReport`)
- Test: `tests/test_services_discovery.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_services_discovery.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.services.agents import DiscoveryBundle
from resume_agent.services.discovery import reprocess_jobs
from resume_agent.tracking.repository import jobs_by_status
from resume_agent.tracking.tables import Job, JobStatus


class _Result:
    def __init__(self, content):
        self.content = content


def _bundle():
    from resume_agent.models.job import JobCriteriaExtract, SponsorshipSignal
    from resume_agent.discovery.fit import FitScore

    extract = type("E", (), {"run": lambda self, p: _Result(JobCriteriaExtract.model_validate(dict(
        sponsorship_signal=SponsorshipSignal.offered, seniority=None, employment_type=None,
        tech_stack=[], industry=None, company_size=None, yoe_min=None, salary_range=None,
        remote_policy=None, location=None, must_have_skills=[], nice_to_have_skills=[])))})()
    fit = type("F", (), {"run": lambda self, p: _Result(FitScore(score=77, rationale="ok"))})()
    return DiscoveryBundle(extract=extract, fit=fit, relevance=None, canonicalizer=None)


def test_reprocess_jobs_rescores_shortlisted(tmp_path):
    facts = tmp_path / "facts.json"
    facts.write_text('{"contact": {"name": "Ada"}}', "utf-8")
    search = tmp_path / "search.yaml"
    search.write_text("titles: []\n", "utf-8")
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        from resume_agent.tracking.repository import save_job
        save_job(s, Job(source="x", jd_text="jd", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=10, criteria_json={}))
        counts = reprocess_jobs(
            s, scopes=["shortlisted"], search_path=str(search), facts_path=str(facts),
            bundle=_bundle(),
        )
        assert jobs_by_status(s, JobStatus.shortlisted.value)[0].fit_score == 77
        assert counts[JobStatus.shortlisted.value] == 1
```

> Confirm the minimal `facts.json` / `search.yaml` shapes load via `load_facts` /
> `load_search_config`; if those loaders require more fields, copy a fixture from an
> existing services/CLI test instead of hand-writing them.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_discovery.py -v`
Expected: FAIL — `reprocess_jobs` undefined.

- [ ] **Step 3: Implement the wrappers**

In `src/resume_agent/services/discovery.py`:

1. Update the pipeline import:

```python
from resume_agent.discovery.pipeline import discover, reprocess
```

2. **Delete** `reextract_metadata` and `rescore_existing` (lines ~112-152).

3. Add a `RefreshReport` dataclass at the top (after the constants):

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RefreshReport:
    pulled: int
    totals: dict[str, int]
    status_counts: dict[str, int]
    failures: dict[str, dict[str, str]]
```

4. Add the two use-cases:

```python
def reprocess_jobs(
    session: Session,
    *,
    scopes: list[str],
    search_path: str = DEFAULT_SEARCH,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Re-run the full funnel over the chosen scopes; returns final status counts."""
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    bundle = bundle or build_discovery_bundle()
    return reprocess(
        session, config, facts, bundle.extract, bundle.fit, scopes,
        relevance_agent=bundle.relevance, canonicalizer=bundle.canonicalizer,
        reporter=reporter,
    )


def refresh_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    facts_path: str = DEFAULT_FACTS,
    limit: int | None = None,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> RefreshReport:
    """Pull from every connector, then discover the newly-added raw jobs, in one pass."""
    pull_report = pull_jobs(
        session, search_path=search_path, connectors_path=connectors_path,
        telemetry_path=telemetry_path, limit=limit, reporter=reporter,
    )
    counts = discover_jobs(
        session, search_path=search_path, facts_path=facts_path,
        bundle=bundle, reporter=reporter,
    )
    return RefreshReport(
        pulled=sum(pull_report.totals.values()),
        totals=pull_report.totals,
        status_counts=counts,
        failures=pull_report.failures,
    )
```

- [ ] **Step 4: Run tests + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_discovery.py -v && ruff check src/resume_agent/services/discovery.py`
Expected: PASS, no unused imports (the `backfill_rescore`/`reextract` imports are gone).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/discovery.py tests/test_services_discovery.py
git commit -m "feat(services): add reprocess_jobs + refresh_jobs; drop dead backfill wrappers"
```

---

## Task 8: CLI — drop modes, add reprocess + refresh

**Files:**
- Modify: `src/resume_agent/cli.py:14,25-31,159-204` and add two commands
- Test: `tests/test_cli_discovery.py`

- [ ] **Step 1: Update the CLI test**

In `tests/test_cli_discovery.py`, **delete** `test_discover_reextract_invokes_reextract` (line ~72) and any `--rescore` test, then append:

```python
def test_reprocess_invokes_service(tmp_path, monkeypatch):
    import resume_agent.cli as cli

    captured = {}

    def fake_reprocess_jobs(session, *, scopes, search_path, facts_path, reporter=None):
        captured["scopes"] = scopes
        return {"shortlisted": 3}

    monkeypatch.setattr(cli, "reprocess_jobs", fake_reprocess_jobs)
    db_url = f"sqlite:///{tmp_path/'t.db'}"
    result = runner.invoke(
        cli.app, ["reprocess", "--scope", "shortlisted", "--scope", "rejected:relevance",
                  "--db-url", db_url],
    )
    assert result.exit_code == 0
    assert captured["scopes"] == ["shortlisted", "rejected:relevance"]


def test_refresh_invokes_service(tmp_path, monkeypatch):
    import resume_agent.cli as cli
    from resume_agent.services.discovery import RefreshReport

    monkeypatch.setattr(Path, "exists", lambda self: True)

    def fake_refresh_jobs(session, **kwargs):
        return RefreshReport(pulled=5, totals={"greenhouse": 5},
                             status_counts={"shortlisted": 2}, failures={})

    monkeypatch.setattr(cli, "refresh_jobs", fake_refresh_jobs)
    db_url = f"sqlite:///{tmp_path/'t.db'}"
    result = runner.invoke(cli.app, ["refresh", "--db-url", db_url])
    assert result.exit_code == 0
    assert "5 pulled" in result.output
```

> Match the file's existing `runner` / `Path` imports; if `Path` isn't imported there,
> add `from pathlib import Path` to the test.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_discovery.py -k "reprocess or refresh" -v`
Expected: FAIL — commands don't exist; `reprocess_jobs`/`refresh_jobs` not imported in `cli`.

- [ ] **Step 3: Update imports**

In `src/resume_agent/cli.py`:
- Line 14: **delete** `from resume_agent.discovery.pipeline import backfill_rescore, reextract`.
- Lines 25-31: extend the services import:

```python
from resume_agent.services.discovery import (
    UrlFetchError,
    add_job_from_text,
    add_job_from_url,
    discover_jobs,
    pull_jobs,
    refresh_jobs,
    reprocess_jobs,
)
```

- Remove now-unused imports `build_extract_agent`, `build_fit_agent` (lines 12-13) **only if** `ruff check` flags them after Step 5; `build_skill_canonicalizer` stays (used by match-gap).

- [ ] **Step 4: Rewrite discover_cmd and add the new commands**

Replace `discover_cmd` (lines 159-204) with the trimmed version:

```python
@app.command("discover")
def discover_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the discovery funnel over new (raw) jobs and report status counts."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = discover_jobs(
            session, search_path=search, facts_path=facts,
            reporter=ProgressReporter("discover"),
        )
    typer.echo(f"Discovery complete. Status counts: {counts}")


@app.command("reprocess")
def reprocess_cmd(
    scope: list[str] = typer.Option(
        ["shortlisted"], "--scope",
        help="Repeatable: shortlisted | rejected:relevance | rejected:filtered | all.",
    ),
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Re-run the full funnel over chosen scopes (can flip fit + status)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = reprocess_jobs(
            session, scopes=scope, search_path=search, facts_path=facts,
            reporter=ProgressReporter("discover"),
        )
    typer.echo(f"Reprocess complete. Status counts: {counts}")


@app.command("refresh")
def refresh_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    limit: int | None = typer.Option(None, help="Cap postings per connector this run."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Pull from connectors then discover the new jobs, in one pass."""
    if not Path(connectors_path).exists():
        typer.echo(
            f"No connectors config found at {connectors_path}. "
            "Copy config/connectors.yaml.example to config/connectors.yaml and edit it."
        )
        raise typer.Exit(code=1)
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = refresh_jobs(
            session, search_path=search, connectors_path=connectors_path,
            telemetry_path=CONNECTOR_RUNS_PATH, facts_path=facts, limit=limit,
            reporter=ProgressReporter("refresh"),
        )
    typer.echo(
        f"Refresh complete. +{report.pulled} pulled. Status counts: {report.status_counts}"
    )
```

> `DEFAULT_CONNECTORS` is referenced by `pull_cmd`; confirm it is defined/imported near
> the other `DEFAULT_*` constants in `cli.py` and reuse it. If `pull_cmd` reads the
> literal `"config/connectors.yaml"` instead, mirror that literal here.

- [ ] **Step 5: Run tests + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_discovery.py -v && ruff check src/resume_agent/cli.py`
Expected: PASS, no unused-import errors (remove any flagged).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_discovery.py
git commit -m "feat(cli): trim discover modes; add reprocess + refresh commands"
```

---

## Task 9: API — endpoints + OpenAPI regen

**Files:**
- Modify: `src/resume_agent/api/schemas/runs.py`
- Modify: `src/resume_agent/api/routers/runs.py`
- Regenerate: `contracts/openapi.json`, `contracts/ts/api.ts`
- Test: `tests/api/test_runs.py` (or nearest existing run-endpoint test), `tests/api/test_openapi_contract.py`

- [ ] **Step 1: Write the failing test**

Append to the API run tests (use the existing TestClient fixture in that file):

```python
def test_reprocess_endpoint_launches_run(client):
    resp = client.post("/api/reprocess", json={"scopes": ["shortlisted"]})
    assert resp.status_code == 202
    assert resp.json()["kind"] == "reprocess"


def test_refresh_endpoint_launches_run(client):
    resp = client.post("/api/refresh", json={"limit": None})
    assert resp.status_code == 202
    assert resp.json()["kind"] == "refresh"
```

> Match the fixture name/shape already used in that test module (e.g. `client` or
> `api_client`). If launching real agents is a problem under test, the existing
> discover/pull endpoint tests show the established monkeypatch pattern — follow it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs.py -k "reprocess or refresh" -v`
Expected: FAIL — 404, endpoints don't exist.

- [ ] **Step 3: Update schemas**

In `src/resume_agent/api/schemas/runs.py`, replace `DiscoverParams` and add the two new ones:

```python
class DiscoverParams(CamelModel):
    # Discover now only runs the funnel over new (raw) jobs. No modes.
    pass


class ReprocessParams(CamelModel):
    scopes: list[str] = ["shortlisted"]


class RefreshParams(CamelModel):
    limit: int | None = None
```

- [ ] **Step 4: Update the router**

In `src/resume_agent/api/routers/runs.py`:

1. Update the services import:

```python
from resume_agent.services.discovery import (
    add_job_from_url,
    discover_jobs,
    pull_jobs,
    refresh_jobs,
    reprocess_jobs,
)
```

2. Update the schema import to add `ReprocessParams, RefreshParams` and keep `DiscoverParams`.

3. Replace `launch_discover` with the modeless version:

```python
@router.post("/discover", response_model=RunOut, status_code=202)
def launch_discover(
    request: Request,
    params: DiscoverParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            return {"statusCounts": discover_jobs(session, reporter=reporter)}

    run_id = mgr.submit("discover", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
```

4. Add two endpoints after `launch_pull`:

```python
@router.post("/reprocess", response_model=RunOut, status_code=202)
def launch_reprocess(
    params: ReprocessParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            return {"statusCounts": reprocess_jobs(session, scopes=params.scopes, reporter=reporter)}

    run_id = mgr.submit("reprocess", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/refresh", response_model=RunOut, status_code=202)
def launch_refresh(
    params: RefreshParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            report = refresh_jobs(session, limit=params.limit, reporter=reporter)
            return {
                "pulled": report.pulled,
                "totals": report.totals,
                "statusCounts": report.status_counts,
                "failures": report.failures,
            }

    run_id = mgr.submit("refresh", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
```

- [ ] **Step 5: Run API tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs.py -v`
Expected: PASS

- [ ] **Step 6: Regenerate the OpenAPI contract + TS client**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS (regenerated `contracts/openapi.json` + `contracts/ts/api.ts` match the live app).

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api/schemas/runs.py src/resume_agent/api/routers/runs.py contracts/ tests/api/
git commit -m "feat(api): modeless discover; add reprocess + refresh run endpoints"
```

---

## Task 10: html_to_markdown at ingest

**Files:**
- Modify: `pyproject.toml:17` (add dependency)
- Modify: `src/resume_agent/discovery/connectors/text.py:10-15`
- Modify: connectors `greenhouse.py`, `lever.py`, `ashby.py`, `google.py`, `remoteok.py`, `tesla.py`, `workday.py`, `adzuna.py`
- Test: `tests/test_connectors_text.py`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, in the dependencies array after `"beautifulsoup4>=4.15.0",`:

```toml
    "markdownify>=0.13.0",
```

Then install: `.venv/Scripts/python.exe -m pip install "markdownify>=0.13.0"`

- [ ] **Step 2: Write the failing test**

Append to `tests/test_connectors_text.py`:

```python
def test_html_to_markdown_preserves_lists_and_headings():
    from resume_agent.discovery.connectors.text import html_to_markdown

    html = "<h2>Responsibilities</h2><ul><li>Build APIs</li><li>Ship features</li></ul>"
    md = html_to_markdown(html)
    assert "Responsibilities" in md
    assert "- Build APIs" in md or "* Build APIs" in md
    assert "Ship features" in md


def test_html_to_markdown_passes_plain_text_through():
    from resume_agent.discovery.connectors.text import html_to_markdown

    assert html_to_markdown("Just plain text").strip() == "Just plain text"


def test_html_to_markdown_empty():
    from resume_agent.discovery.connectors.text import html_to_markdown

    assert html_to_markdown("") == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_text.py -k markdown -v`
Expected: FAIL — `html_to_markdown` undefined.

- [ ] **Step 4: Implement html_to_markdown**

In `src/resume_agent/discovery/connectors/text.py`, below `html_to_text`:

```python
from markdownify import markdownify as _markdownify


def html_to_markdown(raw: str) -> str:
    """Convert posting HTML to readable markdown (headings, bullets, bold preserved).

    Plain-text input passes through essentially unchanged. Used at ingest so the JD
    keeps structure for display while staying readable to the extract/fit agents.
    """
    if not raw:
        return ""
    return _markdownify(html.unescape(raw), heading_style="ATX", bullets="-").strip()
```

(`html` is already imported at the top of `text.py`; if not, add `import html`.)

- [ ] **Step 5: Switch the connectors**

In each connector, change the import and the call site from `html_to_text` to `html_to_markdown` **for HTML payloads only**:

- `greenhouse.py:7,32`: `html_to_markdown(item.get("content", ""))`
- `lever.py:7,35`: `return html_to_markdown("\n".join(part for part in parts if part))`
- `ashby.py:5,14`: `item.get("descriptionPlain") or html_to_markdown(item.get("descriptionHtml", ""))`
- `google.py:6,25`: `jd_text=html_to_markdown(item.get("description", ""))`
- `remoteok.py:6,25`: `jd_text=html_to_markdown(item.get("description", ""))`
- `tesla.py:8,44`: `row.jd_text = html_to_markdown(info.get("description", ""))`
- `workday.py:9,66`: `row.jd_text = html_to_markdown(info.get("jobDescription", ""))`
- `adzuna.py:11,74,101`: `descriptions.append(html_to_markdown(raw))` and `candidates.append(_clean_lines(html_to_markdown(html)))`

Leave `html_to_text` defined (still used by `tests/test_connectors_text.py` and the url_ingest module has its own copy). Update each connector's import line to `from resume_agent.discovery.connectors.text import html_to_markdown` (keep `is_materially_richer`, `primary_search_term` etc. where also imported).

> For `adzuna.py`, verify `_clean_lines` still behaves on markdown (it strips/joins
> lines); markdown bullets are line-prefixed `-`, which `_clean_lines` should leave
> intact. If a test in `tests/` asserts a specific plain-text adzuna shape, update it
> to the markdown equivalent.

- [ ] **Step 6: Run the connector suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_text.py tests/ -k "connector or adzuna or workday or greenhouse or lever or ashby or google or remoteok or tesla" -v && ruff check`
Expected: PASS (fix any connector test that asserted old plain-text output).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/resume_agent/discovery/connectors/ tests/test_connectors_text.py
git commit -m "feat(connectors): store JD as markdown via html_to_markdown at ingest"
```

---

## Task 11: Web — markdown JD renderer

**Files:**
- Modify: `web/package.json` (add `react-markdown`)
- Create: `web/src/lib/format/prettify.ts`, `web/src/lib/format/prettify.test.ts`
- Modify: `web/src/components/JobModal.tsx:96-98`

- [ ] **Step 1: Add the dependency**

```bash
cd web && npm install react-markdown@^9
```

- [ ] **Step 2: Write the failing test for prettifyPlainText**

Create `web/src/lib/format/prettify.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { prettifyPlainText } from "./prettify";

describe("prettifyPlainText", () => {
  it("turns dash-prefixed lines into markdown bullets", () => {
    const out = prettifyPlainText("Responsibilities\n- Build APIs\n- Ship features");
    expect(out).toContain("- Build APIs");
  });

  it("joins blank-line-separated blocks as paragraphs", () => {
    const out = prettifyPlainText("Intro line\n\nSecond block");
    expect(out).toContain("Intro line");
    expect(out).toContain("Second block");
  });

  it("leaves existing markdown bullets alone", () => {
    const out = prettifyPlainText("- already a bullet");
    expect(out.trim()).toBe("- already a bullet");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/format/prettify.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement prettifyPlainText**

Create `web/src/lib/format/prettify.ts`:

```ts
// Legacy JD rows are flat text (structure was stripped at ingest before the
// markdown change). This applies light, conservative heuristics so they render
// with some structure under react-markdown. New (markdown) rows pass through
// untouched because they already contain markdown markers.
const BULLET_LINE = /^\s*[-*•]\s+/;

export function prettifyPlainText(text: string): string {
  if (!text) return "";
  // Already markdown-ish? Leave it alone.
  if (/(^|\n)\s*(#{1,6}\s|[-*]\s|\d+\.\s)/.test(text)) return text;

  return text
    .split("\n")
    .map((line) => {
      const trimmed = line.trimEnd();
      if (BULLET_LINE.test(trimmed)) return trimmed.replace(BULLET_LINE, "- ");
      return trimmed;
    })
    .join("\n");
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/lib/format/prettify.test.ts`
Expected: PASS

- [ ] **Step 6: Render markdown in the modal**

In `web/src/components/JobModal.tsx`:
- Add imports at top:

```tsx
import ReactMarkdown from "react-markdown";
import { prettifyPlainText } from "@/lib/format/prettify";
```

- Replace the `<pre>` block (lines 96-98) with:

```tsx
                      <div className="prose prose-sm mt-3 max-w-none rounded-xl border bg-background/60 p-5 leading-7 dark:prose-invert">
                        <ReactMarkdown>{prettifyPlainText(job.jdText)}</ReactMarkdown>
                      </div>
```

> If the Tailwind typography (`prose`) plugin is not installed, either add
> `@tailwindcss/typography` to `web` and the Tailwind config, or drop the `prose`
> classes and style the container directly (headings/lists inherit sane defaults).
> Verify which by checking `web/tailwind.config.*` for the typography plugin.

- [ ] **Step 7: Run web tests + typecheck**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/src/lib/format/ web/src/components/JobModal.tsx
git commit -m "feat(web): render JD as markdown with legacy plain-text prettifier"
```

---

## Task 12: Web — reprocess + refresh actions

**Files:**
- Modify: `web/src/features/runs/use-launch-run.ts:57-64`
- Modify: `web/src/features/runs/RunLaunchDialogs.tsx`
- Modify: `web/src/features/runs/RunActions.tsx`

- [ ] **Step 1: Update launchers + types**

In `web/src/features/runs/use-launch-run.ts`, replace the `DiscoverMode` type and `launchers`:

```ts
export type ReprocessScope =
  | "shortlisted"
  | "rejected:relevance"
  | "rejected:filtered"
  | "all";

export const launchers = {
  pull: (opts: PullOptions = {}) =>
    unwrap(api.POST("/api/pull", { body: { limit: opts.limit ?? null } })),
  discover: () => unwrap(api.POST("/api/discover", { body: {} })),
  reprocess: (scopes: ReprocessScope[]) =>
    unwrap(api.POST("/api/reprocess", { body: { scopes } })),
  refresh: (opts: PullOptions = {}) =>
    unwrap(api.POST("/api/refresh", { body: { limit: opts.limit ?? null } })),
};
```

(Delete the old `DiscoverMode` type; the generated `api.ts` from Task 9 provides the new path types.)

- [ ] **Step 2: Simplify DiscoverDialog + add Reprocess and Refresh**

In `web/src/features/runs/RunLaunchDialogs.tsx`:
- Replace `DISCOVER_MODES` + `DiscoverDialog` with a modeless discover trigger:

```tsx
export function DiscoverDialog() {
  const { launch } = useLaunchRun();
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() => launch("discover", () => launchers.discover())}
    >
      Discover
    </Button>
  );
}
```

- Add a Refresh button and a Reprocess dialog (scope multi-select). Append:

```tsx
export function RefreshButton() {
  const { launch } = useLaunchRun();
  return (
    <Button size="sm" onClick={() => launch("refresh", () => launchers.refresh())}>
      Refresh
    </Button>
  );
}

const REPROCESS_SCOPES: { value: ReprocessScope; label: string }[] = [
  { value: "shortlisted", label: "Re-score shortlist" },
  { value: "rejected:relevance", label: "Reconsider off-target" },
  { value: "rejected:filtered", label: "Reconsider hard-filtered" },
  { value: "all", label: "Everything (non-submitted)" },
];

export function ReprocessDialog() {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<ReprocessScope>("shortlisted");
  const { launch } = useLaunchRun();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline">Reprocess</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reprocess</DialogTitle>
          <DialogDescription>
            Re-run the full funnel over a scope. Can change fit + status. Submitted jobs
            are never touched.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="reprocess-scope">Scope</Label>
          <Select value={scope} onValueChange={(v) => setScope(v as ReprocessScope)}>
            <SelectTrigger id="reprocess-scope" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REPROCESS_SCOPES.map((s) => (
                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          onClick={async () => {
            const ok = await launch("reprocess", () => launchers.reprocess([scope]));
            if (ok) setOpen(false);
          }}
        >
          Start reprocess
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

- Update the import line to add `ReprocessScope` from `./use-launch-run`.

- [ ] **Step 3: Wire RunActions**

In `web/src/features/runs/RunActions.tsx`:

```tsx
import { AddUrlDialog } from "./AddUrlDialog";
import {
  PullDialog,
  DiscoverDialog,
  ReprocessDialog,
  RefreshButton,
} from "./RunLaunchDialogs";

export function RunActions() {
  return (
    <div className="flex items-center gap-2">
      <RefreshButton />
      <PullDialog />
      <DiscoverDialog />
      <ReprocessDialog />
      <AddUrlDialog />
    </div>
  );
}
```

- [ ] **Step 4: Typecheck + tests**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: PASS. Fix any test that referenced the removed `DiscoverMode`/discover modes (e.g. a `RunLaunchDialogs` test) to use the new components.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/runs/
git commit -m "feat(web): add Refresh + Reprocess actions; modeless Discover"
```

---

## Task 13: Rename Best-have → Nice-to-have

**Files:**
- Modify: `web/src/components/SkillMatrix.tsx:1,90-96`
- Modify: `web/src/components/JobCard.tsx:28`
- Test: `web/src/components/SkillMatrix.test.tsx` (create if absent)

- [ ] **Step 1: Write/extend the failing test**

Create or append `web/src/components/SkillMatrix.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SkillMatrix } from "./SkillMatrix";

describe("SkillMatrix", () => {
  it("labels the optional group 'Nice-to-have'", () => {
    render(
      <SkillMatrix
        skills={[
          { name: "Python", required: true, covered: true },
          { name: "Go", required: false, covered: false },
        ]}
      />,
    );
    expect(screen.getByText("Nice-to-have")).toBeInTheDocument();
    expect(screen.queryByText("Best-have")).not.toBeInTheDocument();
  });
});
```

> Match the real `SkillTag` shape from `@/lib/filters/types` (fields `name`,
> `required`, `covered`); adjust the literals if it has more required fields.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/SkillMatrix.test.tsx`
Expected: FAIL — current label is "Best-have".

- [ ] **Step 3: Rename the label + comments**

In `web/src/components/SkillMatrix.tsx`:
- Line 1 comment: `// Full skill set, grouped Must-have / Nice-to-have. Two independent channels:`
- Line ~91-96: change the second `<Group label="Best-have" ... />` to `label="Nice-to-have"`.

In `web/src/components/JobCard.tsx`:
- Line 28 comment: `// Must-have first, then nice-to-have — same priority the modal groups by.`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/SkillMatrix.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/SkillMatrix.tsx web/src/components/JobCard.tsx web/src/components/SkillMatrix.test.tsx
git commit -m "feat(web): rename Best-have skills label to Nice-to-have"
```

---

## Final verification

- [ ] **Backend full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all PASS, no lint errors.

- [ ] **Web full suite + typecheck + build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all PASS.

- [ ] **OpenAPI drift gate**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS (contracts regenerated and committed in Task 9).

- [ ] **Manual smoke (optional, needs API keys + connectors.yaml):**
  `resume-agent refresh --limit 5` → expect `+N pulled. Status counts: {...}`;
  open a job in the dashboard → JD renders with headings/bullets; the optional skill
  group reads "Nice-to-have".

---

## Self-review notes (coverage check)

- Spec WS1 (incremental discover + reprocess) → Tasks 5, 6, 7, 8, 9.
- Spec WS1b (reject_category) → Tasks 3, 5.
- Spec WS2 (dedup hardening) → Tasks 1, 2, 3, 4.
- Spec WS3 (refresh) → Tasks 7, 8, 9, 12.
- Spec WS4 (markdown JD) → Tasks 10, 11.
- Spec WS5 (rename) → Task 13.
- Risk "markdown shifts dedup/word-count" → covered by Task 4 (fingerprint) + the dedup tests; `is_materially_richer` is exercised by existing `test_same_source_richer_text_refreshes_existing_row`.
- Risk "markdownify dependency" → Task 10 Step 1.
- Risk "abbreviation over-collapse" → Task 1 keeps the map to 6 conservative entries + a distinct-roles test.
