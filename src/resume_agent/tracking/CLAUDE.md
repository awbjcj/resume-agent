# Tracking / board developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/tracking/`.

### Archive, delete, prune and redo

`Job.archived_at` (orthogonal to `status`) soft-hides a job; every view filters
`archived_at IS NULL` — including the dedupe lookup (`find_existing`), so an archived
(trash-binned) duplicate never blocks re-ingesting the same job as a fresh active row.
`has_progress(session, job_id)` — status in
{approved, tailored, rendered} OR any ResumeVersion/CoverLetter OR an
Application carrying real investment — is
the single gate for irreversible paths. `delete_job` refuses jobs with progress and
cascades incidental children in FK-safe order otherwise.

**An `Application` alone is not progress (ADR-0013.)** It counts only when
`status != "ready"`, or notes are non-blank, or it owns any `ApplicationEvent`,
or a resume/cover-letter pointer is set. `upsert_application` writes a row
unconditionally, so bare existence meant merely opening the Tracking tab
locked the job forever. The predicate is one shared SQLAlchemy expression,
`_application_investment_clause`, used verbatim by both `has_progress` and
`progressed_job_ids` — they are the same rule expressed twice, and a
divergence would let the batched path delete what the single path refuses.
Add any future `Application` child table there and both call sites update at
once. `prune_run` (config:
`config/prune.yaml`) archives rejected/low-fit/stale zero-progress jobs, reports
primary reason counts, then hard-deletes archived zero-progress jobs older than
`retention_days`. Surfaced via the web Triage page and
`resume-agent prune [--dry-run]`.

### Artifact deletion — orphan, never cascade

`delete_artifact_rows` (unguarded, mirroring `delete_job_row`) removes resume
versions and cover letters; `services/board.py`'s `delete_resume_versions` /
`delete_cover_letters` apply the gate above it. Four rules:

- **Never cascades.** A revision descended from a deleted version and a cover
  letter drafted from one are independent artifacts, so `CoverLetter.resume_version_id`,
  `ResumeVersion.parent_version_id`, `CoverLetter.parent_id`, and both
  `Application` pointers are set to `NULL` rather than followed. Nothing does
  this for us: the schema declares these as foreign keys but SQLite here runs
  **without `PRAGMA foreign_keys`**, so a dangling id would simply persist.
- **Refuses the applied artifact**, and `deselect_resume_version` /
  `deselect_cover_letter` (`DELETE /api/jobs/{id}/select-resume`,
  `.../select-cover-letter`) are the way past that gate. The guard is only safe
  because it is escapable.
- **All-or-nothing per request.** One unknown or in-use id fails the whole batch
  (`ArtifactDeleteResult.missing_ids` / `blocked_ids` → 404 / 409
  `ARTIFACT_IN_USE`); a partial delete would leave the caller unable to say what
  survived. `api/artifacts.py::raise_for_delete_result` is the one HTTP mapping.
- **Unlinks the PDF** through `tenancy/storage.py::delete_artifact_pdf`, the
  ADR-0008 chokepoint. Every unresolvable-path branch returns `False` instead of
  raising — aborting the row delete because a stored path is unusable (e.g.
  restored from an imported archive) would strand the row permanently. The
  `.content.json` sidecars and `manifest.json` under `output/` are **not**
  touched: they are owned by `export_job_artifacts`, which rewrites the whole
  directory on the next render.

Deleting every artifact does **not** make a job deletable — `has_progress` also
reads status, which is a high-water mark. Pinned by
`test_deleting_every_version_does_not_make_a_progressed_job_deletable`.

### Redo — forward-only, never destructive

`services/redo.py` re-runs any stage (`pull`/`extract`/`tailor`/`render`) over
explicitly chosen jobs at any status. The automatic paths are deliberately
one-way for user-invested rows: `save_or_upgrade()` freezes a materially richer
`jd_text` replacement when `has_progress()` is true, and `reprocess()` skips the
same rows. For an unprogressed extracted/shortlisted row, accepting richer
source text clears its stale criteria and scoring and returns it to `raw`, so
the next discovery pass does not show metadata derived from the truncated copy.
Redo is the explicit escape hatch for progressed rows, never a mode.

Three invariants, all enforced by `tracking/stages.py::advance`:

- **Never regresses.** `JobStatus` is a high-water mark. A rendered job stays
  rendered through a re-pull + re-extract + re-tailor.
- **Never rejects.** `rejected` ranks below `raw`, so the filter and relevance
  gates cannot fire under `never_regress`. Fresh fit scores are still written.
- **Never deletes.** New `ResumeVersion` rows are appended under an incremented
  `attempt`; `tailor_model` records which model produced them.

**These three describe `JobStatus` only.** `ApplicationStatus` follows a
different rule — a progression (`ready < submitted < interview < offer`) that
advances forward only, plus a terminal set (`{rejected, closed}`) reachable
from *any* progression state including `offer`. A flat high-water mark would
block `interview -> rejected`, the most common transition in a job hunt, and
`offer -> rejected`, which is a rescinded offer. The rule lives in
`tracking/status_rules.py`; see ADR-0012. Do not add ordering comparisons
against `ApplicationStatus` members — the ordering lives in `PROGRESSION` and
nowhere else.

`StageScope(job_ids, any_status, never_regress)` is how the funnel stages in
`discovery/pipeline.py` run over explicit ids. `StageScope()` reproduces the
automatic funnel exactly — that default is the regression guard.

Re-pull deliberately bypasses `find_existing`/`decide`/`_apply` and refreshes
the row in place; a `dedup_key` that would collide with a sibling keeps the old
identity and takes only the text.

Per-job stage failures are durable: `services/errors.py::record_job_failure`
writes an `ErrorRecord` with `kind="job"` keyed `job:{id}:{stage}` (so repeats
coalesce into `count`), and `resolve_job_failures` closes it when that stage
later succeeds. `gather_isolated` no longer discards the exception — the cause
reaches the run result, the log, and the dashboard.

---

## Board query and bulk-action design notes

- **Boards page in SQL.** `tracking.board_query` selects only the returned page,
  and row projection happens afterward. `PipelineItem` ships a bounded
  `jdPreview`; the full `jd_text` is available only from `JobDetail`. Two costs
  the page read must not re-incur: `jd_text` stays `defer()`-ed on shortlist and
  triage (only `PipelineRow` reads it — pinned by
  `test_shortlist_and_triage_rows_never_touch_jd_text`), and the `companySize`/
  `skills` token-to-raw-value scans are derived once per request via
  `derive_filter_values` and passed to both `board_page` and
  `board_facet_counts`.
- **`dedup_key` is not unique — location guard.** `compute_dedup_key` stays
  `normalize(company)|normalize_title(title)`; `find_existing` additionally requires
  `locations_compatible` (blank = wildcard, else city-token subset) on its identical-JD,
  dedup_key, and keyless-fingerprint branches (URL match exempt). Multi-location
  same-title requisitions are sibling rows sharing a dedup_key. See
  `docs/adr/0001-dedup-key-plus-location-guard.md`.
- **Board bulk actions are transactional.** `bulk_apply` uses one batched load plus the
  `progressed_job_ids` gate, then one commit. `delete_job_row` is the unguarded cascade shared
  with guarded `delete_job` and prune.
