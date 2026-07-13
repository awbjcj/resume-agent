# Board UX, Async Revise, Import Surfaces, Company Display Names — Design

Date: 2026-07-12
Status: Approved

One UX-maturity pass over the web app, packaged as four independent
workstreams. They share almost no code; plan tasks must be independently
green.

1. Quick actions + list/cards view toggle across the three board pages.
2. Resume and cover-letter revision become background runs.
3. Four import/export surfaces (admin archive, per-user workspace,
   bulk profile upload, jobs-from-file).
4. Company display names: resolve from ATS payloads, heal on re-pull,
   backfill via CLI.

---

## Workstream 1 — Board quick actions + view toggle

### Shared pieces

- **`JobTable` actions column.** `JobTable` gains an optional trailing
  `actions?: (row) => ReactNode` render prop. Each page injects its own
  buttons; the table stays decoupled from mutations. Header cell renders
  only when the prop is present.
- **`useArchiveJob` mutation.** `PATCH /api/jobs/{id}` with
  `{ archived: true }`. On success: invalidate the board query and show a
  toast with an **Undo** action (same PATCH, `archived: false`).
- **`url` on board item schemas.** `ShortlistItem`, `TriageItem`, and
  `PipelineItem` gain `url: str | None`, whitelisted off the existing
  query DTO. Regenerate contracts (`bash scripts/gen_ts_client.sh`);
  the OpenAPI drift gate covers it.
- **Open posting button.** Ghost external-link icon; opens `row.url` in a
  new tab; hidden when `url` is null.

### Per page

- **Shortlist** — new cards/list toggle:
  - `view=cards|list` in the URL search params (shareable, survives
    refresh); last choice remembered in `localStorage` as the default
    when the param is absent.
  - Card footer becomes an action cluster: **Approve** (primary, existing
    `useApprove`), **Archive** (ghost icon, undo toast), **Open posting**.
  - List mode reuses `JobTable` with the same three actions; selection,
    bulk bar, filters, and load-more are shared — only the presentation
    component swaps.
- **Triage** — keeps its table-only layout; per-row actions:
  - **Archive / Restore**, context-aware with the "show archived" switch.
  - **Open posting**.
  - **Delete** with a `ConfirmDialog`. The API's `has_progress` guard
    already refuses deletion of progressed jobs; surface that error as a
    toast verbatim. Bulk delete with preview remains the primary path for
    volume.
- **Pipeline** — the cards/list toggle applies *within* each stage
  section (list mode renders a `JobTable` per stage). `PipelineCard`
  footers and table rows get **Open posting** + **Archive**. Stage moves
  stay bulk-only; a per-card status picker is the modal's job.

Actions live in card footers / a table column — not hover-revealed — so
they are reachable on touch and never shift layout.

---

## Workstream 2 — Revision as a background run

### API

- `POST /api/resume-versions/{version_id}/revise` and
  `POST /api/cover-letters/{cover_letter_id}/revise` stop running the LLM inside the
  request thread. Both return **202 + a Run record** with new run kinds
  `revise` and `cover_letter_revise`.
- Work is submitted through `RunManager.submit` (which already copies the
  tenant context into the worker and the worker opens its own DB session
  bound to the app engine). Progress flows through `ProgressReporter`;
  clients watch `GET /api/runs/{id}/events` or poll the run.
- The run's **result payload carries the new version id** so the UI can
  highlight it on completion.
- **409 same-artifact guard:** submitting a revise while a revise run is
  already active for the same artifact (resume version id, or cover
  letter id) returns 409 (error envelope, code `CONFLICT`). Different
  artifacts and different jobs may revise concurrently. The guard checks the RunManager's active runs; it must be
  enforced server-side because clients cannot know about runs launched
  before a page reload.

### Web

- `useReviseVersion` and the cover-letter revise mutation switch from
  "await the new version" to "launch and track a run" via the existing
  active-run store (`use-active-run`, `use-rehydrate-runs` — reload-safe).
- Submitting clears the instruction input immediately. The parent version
  row shows a "Revision running…" indicator and its revise input is
  disabled; the versions list shows a pending placeholder row tied to the
  run.
- Navigation away is free; the RunPanel and notifications bell reflect
  the active run. On completion: invalidate job detail, the new version
  row appears highlighted, a notification fires.
- On failure: the placeholder becomes an error state showing the run's
  message, with a retry affordance that re-submits the same instruction.

### Error handling

A failed revision writes nothing (`revise_resume_version` only creates a
new version on success), so the parent version is never corrupted and
retry is always safe.

---

## Workstream 3 — Import/export surfaces

### 3a. Admin backup & restore (wire existing endpoints)

- Admin page gains a "Backup & restore" card.
- **Export:** `GET /api/admin/export` via the existing `openDownload`
  short-lived query-token flow (bearer headers cannot ride an `<a>` tag;
  query tokens stay purpose-bound to selected downloads per ADR-0003).
- **Import:** file picker → `POST /api/admin/import` (multipart) behind a
  destructive-confirm dialog — user types `IMPORT` to proceed; copy states
  it replaces the deployment's data. Staged-validation failures surface
  verbatim in the dialog.

### 3b. Per-user workspace export/import (new API + UI)

- New endpoints on the account router:
  - `GET /api/account/export` — archive of the caller's workspace only.
  - `POST /api/account/import` — staged, rollback-safe restore into the
    caller's workspace.
- Both reuse `services/backup.py` scoped to the workspace root resolved
  from `UserContext`. System tables (users, PATs, budgets, invites) are
  never part of these archives; identity and limits are untouched.
- Import returns **409** while the caller has any active run — swapping a
  workspace directory under a running worker is the one real hazard.
- UI on the Account page with the same typed-confirm pattern as 3a.

### 3c. Profile documents bulk upload (no new API)

- Source Manager's file input gains `multiple` plus a drag-and-drop zone.
- Files upload sequentially through the existing single-file endpoint.
  The chosen mode (literal/synthesis, plus anchor for synthesis) applies
  to the whole batch.
- A batch summary reports per-file success/failure; one failure never
  aborts the rest.

### 3d. Jobs from file

- **CSV/JSON (synchronous):** new `POST /api/jobs/import` (multipart).
  - CSV with fixed, documented columns:
    `title, company, url, location, jd_text, posted_at`.
    JSON: an array of objects with the same keys.
  - Rows flow through `save_or_upgrade` with `source="manual"` — dedup,
    the location guard, and source-priority apply unchanged.
  - Response reports added/upgraded/skipped counts plus per-row errors
    (row number + reason). No LLM work; scoring happens on the next
    discover.
- **URL list (background run):** new `POST /api/jobs/import-urls` accepts
  a plain text file, one URL per line, and returns **202 + a run** (kind
  `import_urls`). Each URL goes through the existing add-from-URL
  pipeline with per-URL failure isolation: failures are collected in the
  run result and never abort the batch.
- UI: one "Import file" dialog beside the existing Add-from-URL entry
  point and reachable from the Triage page. The dialog routes by file
  type (`.csv`/`.json` → synchronous import with a results summary;
  `.txt` → background run tracked like any other).

---

## Workstream 4 — Company display names

### Resolve at fetch time

Precedence for a job's `company`:
**configured label/`company` → payload-resolved name → raw token.**

- Greenhouse: fetch the board's `name` from the board API (one extra
  request per board per pull, cached for the pull).
- Ashby: organization title from the job-board payload.
- Workday: posting-info company field when present, else tenant.
- SmartRecruiters, Recruitee, Breezy, Personio: already resolve from
  payloads — unchanged.
- Lever, JazzHR, BambooHR: payloads carry no organization name; keep
  configured-label-or-token. No guessing — if the payload doesn't say,
  we don't invent a prettier name.

### Heal on re-pull

- Today an equal-tier duplicate is a pure no-op (Skip), so a corrected
  label never reaches existing rows.
- The pure merge-decision layer gains one narrow action
  (`RefreshCompany`): when the match is otherwise a Skip **and** the
  incoming company differs **and** the existing row's company equals that
  source's token (case-insensitive), refresh `company`.
- Because `dedup_key` embeds `normalize(company)`, the refresh recomputes
  `dedup_key` (and any company-derived fingerprint) atomically with the
  rename — otherwise the same posting re-ingests as a "new" job on the
  next pull.
- Status, `Application`, `ResumeVersion`, `CoverLetter`, and `jd_text`
  are untouched; the frozen-JD rule is not violated.

### Backfill the long tail

- Jobs no longer present on a board never re-pull. New CLI command:
  `resume-agent fix-company-names [--dry-run]`.
- Walks configured source units, maps token → label/resolved name, and
  updates rows whose company matches the token (same dedup-key recompute
  rules). Reports per-source update counts; `--dry-run` prints without
  writing.
- Web users get the organic heal on every pull; the CLI covers archived
  history.

---

## Testing

All offline, per the existing suite conventions (agents and browser
faked; connectors against fixture JSON).

- **W1:** vitest for `JobTable` actions column, view toggle persistence,
  archive-undo flow, triage delete confirm; existing container tests
  extend to the new footers.
- **W2:** pytest for the 202 + run-record contract, the 409 same-version
  guard, and run result payloads (RunManager already has offline test
  patterns); vitest for pending-row rendering and mutation → run-store
  wiring. Contract regen + drift gate.
- **W3:** pytest for account export/import (tenant-scoped roots, 409 on
  active run, staged rollback on invalid archive) and jobs import
  (CSV/JSON parsing, per-row errors, dedup pass-through, URL-list run);
  vitest for the admin/account cards and the import dialog routing.
- **W4:** pytest with fixture payloads for each resolving backend, the
  `RefreshCompany` merge action (including dedup-key recompute), and the
  backfill command via the CLI test harness.

## Out of scope

- Keyboard triage (j/k navigation) — explicitly deselected.
- Per-card status picker on Pipeline; stage moves stay bulk-only.
- Web UI for the company-name backfill (CLI + organic heal cover it).
- Render and other fast endpoints stay synchronous.
- Column mapping / arbitrary schemas for CSV import; columns are fixed.
