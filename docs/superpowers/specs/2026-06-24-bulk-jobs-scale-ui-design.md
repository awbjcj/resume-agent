# Scaling the Job-Management UI (pull / triage / discover / tailor) — Design

**Date:** 2026-06-24
**Status:** Approved (design); pending implementation plan
**Surface:** `api/` (board + bulk endpoints, schemas), `services/board.py` (server-side filter/facet/bulk), `tracking/queries.py` + indexes, `web/` (filter control, dense table, selection + bulk engine)

---

## 1. Problem & Goal

A single user's pipeline can accumulate **1k–10k jobs per stage** (especially raw +
rejected in Triage). The current React surface does not scale to that:

- **Loading.** Every board hook calls `fetchAllPages` (200 rows/request, looped) and
  then filters, sorts, and computes facets **in the browser** (`web/src/lib/filters/*`).
  At 10k rows that is dozens of sequential round-trips, large payloads, and a heavy
  client compute pass on every keystroke.
- **Selection.** `MultiSelect.tsx` is a checkbox-in-a-dropdown ("Any / 3 selected") —
  you can't see available or selected values without opening each one. Job selection
  is per-card checkboxes with no select-all, no range-select, no "select all matching".
- **Bulk actions are N+1.** Triage archive/delete fire **one HTTP request per job**
  (`selected.forEach(id => mutate(id))`). Hundreds of rejected jobs = hundreds of requests.
- **Filtering is split & partial.** Shortlist has rich client facets; **Triage has no
  filters at all**; the server only knows `minFit`/`sort`/`status`.
- **Pruning at scale is coarse.** `PrunePanel` is a fixed threshold tool; there is no
  "filter to a kind of job → act on all of it" flow.

**Goal:** make 1k–10k jobs per stage fast to load, filter, select, and bulk-act on;
replace the dropdown multi-select with a compact, legible filter control; and turn
pruning rejected jobs into a filter-driven bulk operation — without breaking the
core domain invariants.

---

## 2. Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Target scale | **1k–10k jobs per stage** |
| Backbone | **Server-side filter + act-by-query** (filter/sort/paginate on the server; bulk actions take the same filter query, not an id list) |
| What "server-side" means | **In-process Python filtering inside `services/board`** (Approach A preserved — criteria stay in `criteria_json`; rows are loaded once and filtered/counted in Python). One HTTP round-trip per page; **not** SQL WHERE on every facet. |
| View mode | **Dense table for bulk stages (Triage/prune); cards for the review stage (Shortlist)**; Pipeline keeps stage groups |
| Filter control | **B+C hybrid:** inline toggle-**pills** for fixed enums; compact searchable **popover-chips** for long/data-driven lists |
| Pills (C) | Remote, Seniority, Type, Sponsorship, **Source**, **Company-size** (all fixed enums) |
| Popover-chips (B) | **Skills, Industry, Country, State, City** (long / data-driven) |
| Scalars | Min fit (slider), Min salary (input), Sort (select) — unchanged controls |
| Selection model | **Two-tier:** header box selects loaded page (id mode); banner escalates to "select all N matching" (query mode); shift-click range within loaded rows |
| Delete safety | **Act-by-query with previewed-count confirm** (`dryRun` returns affected/skipped); progress rows always excluded server-side |
| Bulk scope | **All stages, stage-appropriate actions** — Triage: Archive/Delete/Restore · Shortlist: Approve/Archive · Pipeline: set-status/Archive |
| Pruning | Threshold panel → **one-click quick-filters** that populate the filter bar; then select-all-matching → Archive/Delete with previewed count |
| Compactness | Explicit polish requirement: filter rows tight, aligned, dense |

**Deferred (YAGNI v1):** Saved/named views; list virtualization beyond infinite
scroll; advanced facet-count semantics beyond the one described in §3.2.

---

## 3. Architecture

Layered so each unit is independently testable. The client stops owning filter/sort
compute; the `board` service becomes the single filter/facet/bulk authority used by
**both** the API and (via the same service) Streamlit.

```
                          ┌─────────────── services/board.py ───────────────┐
tracking/queries (load) ─▶│ list_<board>(filter)  facets(board, filter)      │
   + DB indexes           │ bulk_apply(board, filter|ids, action, dryRun)    │
                          └───────────────┬──────────────────────────────────┘
                                          │  (Pydantic camelCase contract)
                      GET /api/{board}?<BoardFilter>   POST /api/jobs/bulk
                                          │
        web: useJobQuery (useInfiniteQuery) · useSelection · useBulkAction
                                          │
        FacetPills · FacetPopover · ActiveFilterSummary · JobTable · BulkActionBar
```

### 3.1 `BoardFilter` contract (server + wire)

One filter shape drives lists, facets, and bulk. Wire format is camelCase per the
`CamelModel` convention; multi-value facets are comma-joined query params (preserving
today's `use-board-filters` URL convention so filters stay bookmarkable).

Fields: `minFit`, `minSalary`, `q`, `sort`, plus multi-value
`source`, `remote`, `seniority`, `employmentType`, `sponsorship`, `companySize`,
`skills`, `industry`, `country`, `region`, `city`. (`archived`/`status` already exist
for Triage/Pipeline.) Semantics match today's `apply_filters`: non-skill facets AND
together; skills OR within themselves; a `None` metadata value is not excluded unless
the filter targets "unknown"; `minSalary` excludes only when `salary_max` is known and
below the floor.

### 3.2 Server-side list, sort, paginate, facets (`services/board.py`)

`list_<board>(session, filter, page, page_size)` loads the board rows once (as today),
applies the full `BoardFilter` in Python, sorts, and paginates — returning a `Page`
**plus a `facets` block and `total`**. The list response carries:

- `data` — the page of rows (camelCase board item).
- `pagination` — `{ page, pageSize, totalPages, total }` (matched count).
- `facets` — for each facet, its values with counts. **Count semantics:** each facet's
  counts are computed against the active filter **excluding that facet's own
  selections** (standard faceted behavior, so you can still see and add siblings).
  This is N small in-Python group-bys over the already-loaded rows — fine at 1k–10k.

The existing `lib/filters/apply|sort|facets` compute on the React side is **retired**;
the equivalent logic lives once in `board` (reusing the existing
`dashboard/filtering.py` predicate as the basis, so there is a single implementation).

### 3.3 Bulk act-by-query (`services/board.py` + `POST /api/jobs/bulk`)

```
POST /api/jobs/bulk
{ board, filter?, scope: "query" | "ids", ids?, action, status?, dryRun? }
action ∈ { archive, restore, delete, approve, setStatus }
→ { affected, skipped, reasons: { hasProgress: n, ... } }
```

- `scope:"query"` resolves the matching id set server-side from `board` + `filter`;
  `scope:"ids"` uses the explicit list. Either way the mutation is **one HTTP request**.
- `dryRun:true` returns the same `{affected, skipped, reasons}` **without mutating** —
  this powers every confirm dialog's previewed count.
- **Invariants enforced server-side, per matching job:**
  - `delete` reuses the existing `delete_job` FK-safe cascade and **skips
    `has_progress` rows**, reporting them in `reasons.hasProgress`.
  - `archive`/`restore` set/clear `archived_at` (orthogonal to status; reversible).
  - `approve`/`setStatus` reuse `board.set_stage`; never touch progress jobs' frozen
    `jd_text` (source-priority invariant untouched — this path only changes status).
- `POST /api/prune` (CLI/cron threshold semantics) is **unchanged and kept**; the UI no
  longer calls it.

### 3.4 Indexes (`tracking/`)

Add SQLite indexes on the **real columns** used for server filter/sort at 10k:
`status`, `archived_at`, `fit_score`, `source`, `company`. Criteria-derived facets
(seniority, industry, skills, …) remain JSON-blob, filtered in Python (Approach A) —
no new columns, no migration beyond index creation.

### 3.5 Client data layer (`web/`)

- **`useJobQuery(board)`** — owns `BoardFilter` state ↔ URL searchParams ↔ API via
  `useInfiniteQuery`; returns `rows`, `facets`, `total`, `fetchNextPage`,
  `hasNextPage`. Replaces `useShortlist`/`useTriage`/`usePipeline`'s `fetchAllPages`
  and the entire `lib/filters/apply|sort|facets` path (`normalize` + `types` stay).
- **`useSelection()`** — holds `{ mode: "ids", ids: Set<number> } | { mode: "query" }`.
  Header box → ids of loaded page; banner escalates to `mode:"query"`; shift-click
  selects a range across loaded rows; clearing resets to empty ids.
- **`useBulkAction(board)`** — POSTs `/api/jobs/bulk`; sends `filter` when
  `mode:"query"`, else `ids`; supports a `dryRun` preview call; invalidates the board
  query and any cross-board caches on success.

### 3.6 Filter control rebuild (`web/src/components/`)

Replace `MultiSelect.tsx` + `FilterDesk.tsx` with focused, independently-testable units:

- **`FacetPills`** (C) — fixed enums as one-click toggle pills, all values visible:
  Remote, Seniority, Type, Sponsorship, Source, Company-size. Selected = filled pill.
- **`FacetPopover`** (B) — long/data-driven lists as a compact chip with a count badge;
  click opens a searchable, counted checkbox list: Skills, Industry, Country, State, City.
- **`ActiveFilterSummary`** — every active filter as a removable chip + live
  "N of M match" (from `facets`/`total`) + Clear all.
- Scalars (`Min fit` slider, `Min salary` input, `Sort` select) retained.
- **Polish requirement:** rows tight, aligned to a consistent baseline grid, dense;
  no orphaned/ragged controls.

### 3.7 Views & bulk surface

- **Triage → `JobTable`** (dense, sortable): columns checkbox · Company·Title · Fit
  (color chip) · Source · Location · Age · Status. Header sort; shift-select; infinite
  scroll on `fetchNextPage`.
- **Shortlist** keeps the **card grid** (decision surface) + a `BulkActionBar` adding
  bulk **Approve**/Archive over the existing per-card Approve.
- **Pipeline** keeps stage groups + bulk **set-status**/Archive.
- Shared **`BulkActionBar`** + **two-tier select-all banner** across all three.

### 3.8 Pruning reimagined (`web/src/features/triage/`)

`PrunePanel` is replaced by one-click **quick-filter presets** that populate the
`BoardFilter` bar — e.g. *Low-fit (`<40`)*, *Stale (`>45d`)*, *Off-target rejected*.
Flow: pick a quick filter (or build one) → **Select all N matching** → **Archive/Delete**
→ confirm dialog shows the `dryRun` preview ("4,180 archive · 30 skipped (progress)")
→ one bulk call. Threshold semantics that belong to cron stay in `POST /api/prune`.

---

## 4. Error handling & edge cases

- **Empty filter result** — `EmptyState` ("No jobs match these filters") with a Clear-all
  affordance, not a blank table.
- **Selection vs. filter change** — changing the filter while a `mode:"query"` selection
  is active re-scopes "all matching"; changing it with a `mode:"ids"` selection clears
  ids that left the result set (and the banner) to avoid acting on stale ids.
- **All rows progress-guarded** — bulk Delete preview shows `affected:0, skipped:N`; the
  confirm's primary action is disabled with an explanatory note.
- **Bulk partial outcome** — response `reasons` is surfaced in a toast ("4,180 deleted ·
  30 skipped — have progress").
- **Facet with zero matches under current filter** — value still listed (count 0) in its
  own facet (excluded-self semantics), hidden in others.
- **Token/empty board** — `useInfiniteQuery` handles auth + empty first page gracefully.

---

## 5. Testing strategy (offline; agents + network faked)

- **`services/board`** — table-driven: each facet in isolation, AND combination, skills
  OR, unknown-value pass-through, salary-floor exclusion, every sort key, pagination
  boundaries, facet-count excluded-self semantics, `total` correctness.
- **`bulk_apply`** — archive/restore/delete/approve/setStatus by query and by ids;
  `has_progress` skip + `reasons`; `dryRun` mutates nothing; FK-safe delete cascade.
- **API contract** — new `BoardFilter` params, `facets`/`total` in the list envelope,
  `/api/jobs/bulk` request/response; regenerate `contracts/openapi.json` + TS client;
  the `tests/api/test_openapi_contract.py` drift gate must pass.
- **Client** — `useSelection` (page select, banner escalation, shift-range, filter-change
  invalidation), `useBulkAction` (query vs ids payload, dryRun), `FacetPills`/
  `FacetPopover`/`ActiveFilterSummary` interactions, `JobTable` selection + sort.
- **Indexes** — a migration/startup test that index creation is idempotent on an
  existing DB.

---

## 6. Out of scope (YAGNI)

- Saved/named filter views.
- List virtualization beyond infinite scroll (only if 10k pages still feel heavy).
- Promoting criteria fields to SQL columns (Approach B) — Approach A retained.
- Bulk actions on Analytics/Match-gap surfaces.
- Cross-stage "move N jobs to stage X" beyond the per-board `setStatus`.

---

## 7. Relationship to in-flight work (must reconcile)

- **`docs/superpowers/plans/2026-06-23-shortlist-filter-contract.md`** exists to keep the
  **Python (Streamlit) and TypeScript (React) filter implementations** in sync because
  filtering runs in two runtimes. **This design removes the React-side filter compute**
  (the server owns it), which collapses that two-runtime problem: React no longer
  filters, so the cross-language TS conformance harness becomes moot for the React path.
  Filtering consolidates into the `board` service (one Python implementation behind the
  API, reused by Streamlit). **Action:** before executing this design, decide whether to
  (a) pause/retire the TS half of the filter-contract plan and keep a single
  API-level golden-fixture test of `board` filtering, or (b) land the contract first as a
  safety net and retire the TS harness as part of this work. Recommended: (b) — keep the
  Python predicate contract, drop the TS harness when `useJobQuery` lands.
- **`docs/superpowers/specs/2026-06-16-job-metadata-filtering-design.md`** locked
  **Approach A** (in-memory filtering, criteria in `criteria_json`). This design honors
  it: server-side filtering is in-process Python, not new SQL columns.
- **`docs/superpowers/plans/2026-06-23-board-single-seam.md`** (board seam work) — the
  new `list_<board>(filter)` / `facets` / `bulk_apply` functions should land on that
  single seam, not a parallel one.

---

## 8. Build sequence (for the implementation plan)

1. **`BoardFilter`** schema + server-side filter/sort/paginate in `board.list_<board>`
   (port the `dashboard/filtering.py` predicate) + `facets`/`total` in the list envelope (+ tests).
2. **DB indexes** on status/archived_at/fit_score/source/company (+ idempotent test).
3. **`bulk_apply`** + `POST /api/jobs/bulk` (query/ids, all actions, dryRun, progress
   skip) (+ tests); regenerate OpenAPI + TS client.
4. **`useJobQuery`** (infinite) replacing `fetchAllPages`; retire client `lib/filters`
   compute (+ client tests).
5. **`useSelection`** + **`useBulkAction`** (+ tests).
6. **Filter control rebuild** — `FacetPills` / `FacetPopover` / `ActiveFilterSummary`
   replacing `MultiSelect` + `FilterDesk` (+ tests, compactness polish).
7. **Triage `JobTable`** + `BulkActionBar` + two-tier banner; **quick-filter prune** (+ tests).
8. **Shortlist** bulk Approve/Archive bar (cards retained) (+ tests).
9. **Pipeline** bulk set-status/Archive (+ tests).
10. Manual headless dashboard verification across all three boards at scale.
