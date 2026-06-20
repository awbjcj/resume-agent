# Job lifecycle management — archive, delete, prune

**Date:** 2026-06-20
**Status:** Approved (design); pending implementation plan

## Problem

The dashboard can surface and advance jobs but cannot *remove* them. There is no
way to delete a job, no way to clear out auto-rejected or low-relevance noise, and
raw/pre-shortlist jobs are only visible as read-only groups inside the heavy
Pipeline board. The Pipeline board itself has no filtering, sorting, or stage
controls. We need job lifecycle management — manual delete, automatic pruning, a
dedicated triage surface, and richer pipeline controls — **without** violating the
project's "user progress is sacred" invariant.

## Goals

- Manually archive (reversible) and delete (irreversible) jobs from the dashboard.
- Automatically prune junk (auto-rejected, low-fit, stale) into a recoverable trash bin.
- Give raw / pre-shortlist jobs a dedicated, low-weight triage surface with bulk actions.
- Add filtering, sorting, stage controls, and per-card actions to the Pipeline board.
- Enforce the invariant in exactly one place, not ad hoc per UI handler.

## Non-goals (out of scope for v1)

- "Promote to shortlist" from Triage (deferred follow-up; keeps v1 focused on removal).
- Scheduled/automatic prune on every `discover` run (trigger is manual button + CLI only).
- Bulk *stage* moves on the Pipeline board (manual stage change is per-card).
- Undo for hard-delete (only archive is reversible, by design).

## Core decisions (resolved via grilling)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Delete model | Tiered: archive is the default; hard-delete only for zero-progress jobs |
| D2 | Archive storage | Orthogonal `archived_at` column (lossless, status preserved) |
| D3 | Prune action | Trash-bin: archive now, retention sweep hard-deletes later |
| D4 | Prune criteria | `rejected` OR `fit_score < threshold` OR `stale > N days` |
| D5 | Prune trigger | Manual dashboard button (preview + confirm) + `resume-agent prune` CLI |
| D6 | Config home | `prune.yaml` defaults + dashboard per-run override |
| D7 | Raw jobs home | New lightweight "Triage" page |
| D8 | Triage UX | Checkbox cards + sticky action bar; reused for archived-view restore |
| D9 | Pipeline controls | Filter/sort bar + per-card archive/delete + manual stage change + collapsible groups |
| D10 | Confirmation | Asymmetric: archive instant + Undo; hard-delete/expire `st.dialog` modal |

## Architecture

The spine is **one orthogonal flag + one safety predicate**:

- `Job.archived_at` makes hiding reversible and lossless.
- `has_progress(session, job_id)` is the single chokepoint every irreversible path
  must pass. The invariant lives here, once.

Everything else — Triage page, pipeline controls, CLI — is a surface that calls
these two primitives.

### 1. Data model & migration

- New column: `Job.archived_at: datetime | None = Field(default=None, index=True)`.
- `ensure_archived_at_column(engine)` in `tracking/migrate.py` — idempotent via
  `PRAGMA table_info(jobs)` + `ALTER TABLE`, plus `CREATE INDEX IF NOT EXISTS`.
  Wired into `init_db` after the existing `ensure_*_column` calls.

### 2. The safety predicate

`has_progress(session, job_id) -> bool`:

- `True` if `status ∈ {approved, tailored, rendered}`, **or**
- any `Application`, `ResumeVersion`, or `CoverLetter` row references the job.

`is_deletable = not has_progress`. Gates every hard-delete and every prune-expire.

### 3. API / repository layer (`tracking/repository.py`)

- `archive_job(session, job_id) -> Job | None` — set `archived_at = utcnow()`.
- `restore_job(session, job_id) -> Job | None` — set `archived_at = None`
  (status untouched, so restore is lossless).
- `delete_job(session, job_id) -> bool` — re-check `has_progress`; if progress,
  refuse and return `False`. Otherwise delete children
  (`CoverLetter` → `ResumeVersion` → `Application`) then the `Job` in **one
  transaction** — a defensive cascade that does not depend on SQLite's FK pragma.
- **Blast-radius update:** `shortlist_rows`, `pipeline_rows`, `status_counts`, and
  the discovery selects gain `WHERE archived_at IS NULL` so archived jobs vanish
  from every normal view.

### 4. Prune engine — pure predicates + thin orchestrator

Mirrors the `filtering.py` (pure) / `pages.py` (DB) split.

New module `tracking/prune.py`, **pure** over plain rows/dataclasses:

- `is_zero_progress(row) -> bool` (data-level mirror of `has_progress`).
- `prune_candidates(rows, config, now) -> list` — selects rows where
  `(status == "rejected" OR fit_score < fit_threshold OR age_days > stale_days)`
  **AND** zero-progress **AND** `archived_at is None`. Each enabled predicate is
  individually toggleable via config.
- `expire_candidates(rows, config, now) -> list` — archived rows where
  `archived_at` is older than `retention_days` **AND** zero-progress.

Orchestrator: `prune_run(session, config) -> PruneReport(archived, expired,
skipped)` lives in `tracking/repository.py` (the session-based layer), keeping
`prune.py` purely functional like `filtering.py`. `PruneReport` is a frozen
dataclass defined alongside the pure predicates in `prune.py`.

- `archived` — count newly archived this run.
- `expired` — count hard-deleted by the retention sweep.
- `skipped` — count that matched a prune predicate but were kept because they had
  progress (telemetry, so the user sees why something survived).

Archived jobs **with** progress are never auto-expired; they stay archived forever.

### 5. Config — `prune.yaml` + `prune_config.py`

Mirrors `search_config.py`:

```yaml
# config/prune.yaml
fit_threshold: 40
stale_days: 60
retention_days: 30
enable_rejected: true
enable_low_fit: true
enable_stale: true
```

`PruneConfig` dataclass + `load_prune_config(path)` with these defaults when the
file is absent. The dashboard pre-fills its prune panel from this; the CLI reads
the same. Dashboard edits are per-run overrides, not persisted.

### 6. CLI (`cli.py`)

`resume-agent prune [--dry-run] [--fit N] [--stale-days N] [--retention-days N]`:

- `--dry-run` computes and prints the preview counts without writing.
- Otherwise applies `prune_run` and reports `+N archived, M expired, K skipped`
  in the `run_pull` telemetry style.
- Flags override `prune.yaml` for that invocation.

### 7. Dashboard surfaces

Sidebar order becomes: **Shortlist · Triage · Pipeline board · Analytics · Match-gap**.

**New Triage page** (`render_triage_page`) — for raw/extracted/filtered/rejected:

- Control desk: filter by status / min-fit / age, sort by fit / recency / company.
- **Checkbox cards + sticky action bar.** Selection lives in
  `st.session_state["triage_selected"]` (a set of `job_id`); each card checkbox is
  keyed `sel-{job_id}` and survives reruns. Action bar: *Archive selected* /
  *Delete selected* (delete only enabled when every selected job `is_deletable`).
- **"Show archived" toggle** reuses the same cards to list archived jobs with a
  per-card / bulk **Restore**.
- **Prune panel:** config-driven preview ("N rejected · M low-fit · K stale →
  archive; J → expire"), tweakable inputs, and a *Prune now* button.

**Pipeline board** (`render_pipeline_page`) gains:

- A filter/sort control desk (it has none today).
- **Collapsible stage groups** (one `st.expander` per status section).
- Per-card **Archive** / **Delete** (delete rendered only when `is_deletable`).
- **Manual stage change**: a `JobStatus` selectbox distinct from the existing
  application-status (employer-funnel) selectbox.

**Confirmation (asymmetric):**

- Archive: one click → `st.success` + an Undo affordance (calls `restore_job`).
- Hard-delete & prune-expire: `st.dialog` modal showing the count + "This cannot
  be undone," acting only on confirm.

### 8. Testing (offline, fakes — per the project test philosophy)

- **Pure:** `prune_candidates`, `expire_candidates`, `is_zero_progress`, selection
  helpers, `triage_rows` / `archived_rows` builders, and that
  `shortlist_rows` / `pipeline_rows` / `status_counts` exclude archived rows.
- **Repository:** `archive_job` / `restore_job` round-trip (status preserved),
  `delete_job` cascade + refusal when progress exists, `prune_run` report counts
  (archived / expired / skipped, including the progress-skip path).
- **CLI:** `prune --dry-run` writes nothing; `prune` applies and reports.
- **Migration:** `ensure_archived_at_column` is idempotent on repeated calls.

## Risks & mitigations

- **Selection-state fragility** (D8 is the most custom Streamlit work): keep the
  selection set keyed strictly by `job_id`, prune stale ids on each render, and
  cover the helper logic with pure unit tests so the DOM wiring is the only
  untested part.
- **Blast radius of the archived filter:** every status query must add the
  `archived_at IS NULL` guard or archived jobs leak back into views — enumerated
  in §3 and covered by tests in §8.
- **`st.dialog` availability:** requires a recent Streamlit (already in use per the
  1.58 DOM notes); if unavailable, fall back to a two-step inline confirm.
