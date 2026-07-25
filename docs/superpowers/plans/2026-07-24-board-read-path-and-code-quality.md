# Board Read Path & Code Quality Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with test-driven
> development. This run is explicitly inline: do not delegate to subagents.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the board read path cost what its SQL costs, delete the dead cross-language filter machinery that is hiding a user-visible ranking regression, and stop shipping 287 KB of job description to render three clipped lines of text.

**Architecture:** Two deepenings and one deletion. `services/board.py` is today a **shallow in-memory query engine** — it reimplements `WHERE`/`ORDER BY`/`LIMIT`/`GROUP BY` in Python over `list[Any]` rows reached by `getattr` string lookups, after `tracking.queries` has already materialised every row in the table. The deepening turns the **Board seam** into a real query: one statement builder that pushes filter, sort and page into SQL and projects only the page. The deletion removes the **Filter contract** and its Python half, whose TypeScript half no longer exists — a seam with zero adapters.

**Tech Stack:** Python 3.13, FastAPI, SQLModel/SQLAlchemy 2.x, pydantic v2, pytest (offline — every agent and the browser are faked), Typer CLI, React 19 / TS web with `openapi-fetch` against a generated client.

---

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline; no API key, no network). Lint: `ruff check`. Web: `cd web && npm run test:run`.
- Keep per-task verification focused on the behavior just changed. Run the full
  Python/web/lint/build matrix once at the end.
- **Baseline is green:** the full suite passes at plan authoring time (exit 0, slowest single test 6.87 s). Any red test during execution is caused by the task in flight.
- **Contract policy:** Phases 0, 2 and 5 must leave the generated OpenAPI
  artifacts byte-identical. Phase 1 adds the `preset` query parameter, Phase 3
  replaces `jdText` with `jdPreview`, and Phase 4 makes `facets` nullable; those
  three tasks regenerate `contracts/openapi.json`, `contracts/ts/api.ts`, and
  `web/src/lib/api/schema.ts`. `tests/api/test_openapi_contract.py` is the drift
  gate after each intentional contract change.
- Behaviour-preserving unless a task says otherwise. Phase 1 Task 3 and Phase 3 change behaviour deliberately and say so.
- Vocabulary: use CONTEXT.md terms (**Board seam**, **JobDetailRow**, **Workspace**, **UserContext**). Phase 6 removes three now-false terms and adds two.
- Windows dev box: invoke Python as `.venv/Scripts/python.exe` exactly as written.
- Commit after every task (small, single-purpose commits). Branch off `dev`, PR into `dev`.
- **Never run `git add -A` or `git add .`** — stage explicitly.
- **Concurrent unrelated work in the tree at authoring time** — a parallel
  session is editing `web/src/components/FilterDesk.tsx` (adds an `excludeSorts`
  prop, renames `SORT_ITEMS` to `ALL_SORT_ITEMS`),
  `web/src/lib/filters/types.ts` (**drops `"stage"` from `SortKey`**),
  `web/src/features/pipeline/PipelineContainer.tsx`,
  `web/src/features/runs/use-approved-launch-jobs.ts` and
  `web/src/features/interview/NewInterviewDialog.tsx`. The same concurrent
  change has already switched the pipeline server default from `stage` to
  `recency`. **Never stage the five web files with a plan commit.** Two
  consequences:
  - `composite` and `preset` both survive that change, so Task 3 is unaffected.
  - `"stage"` is gone from the client and the pipeline endpoint now defaults to
    `recency`. Task 5 Step 5 still preserves `stage` ordering server-side as a
    legacy accepted query value; existing callers may depend on that observable
    behavior even though the current client no longer emits it.

---

## Baseline — measured, not assumed

All numbers below were taken on the real development workspace at
`data/users/1398ad91b2b2/resume_agent.db` (19 MB; **2096 jobs**; 11.7 MB of
`jd_text`; 822 shortlisted of which 99 unarchived; 1244 triage-status; 0
applications). Timings are the **minimum of 3 warm in-process runs** — i.e. the
optimistic case, excluding HTTP, JSON encoding over the wire, and network.

### Where a board request spends its time

| Call                                        | Rows |                        Time |
| ------------------------------------------- | ---: | --------------------------: |
| `queries.triage_rows` (jd_text deferred)    | 1244 |                  **1.4 ms** |
| `queries.shortlist_rows` (jd_text deferred) |   99 |                 **62.4 ms** |
| `queries.pipeline_rows` (jd_text hydrated)  | 2096 |                **232.3 ms** |
| `list_board("triage")` page 1               |      |                  **2.4 ms** |
| `list_board("shortlist")` page 1            |      |                 **65.4 ms** |
| `list_board("pipeline")` page 1             |      | **261.6 ms** (median 303.5) |
| `list_board("pipeline", q="python")` page 1 |      | **316.7 ms** (median 356.5) |
| `list_board("pipeline")` **page 40 of 42**  |      |                **219.2 ms** |

That last row is the diagnosis in one line: **the last page costs the same as
the first.** There is no early-out — every request materialises the whole table
before `paginate()` slices 50 rows out of it.

### cProfile — 3 × `list_board("pipeline", q="python")`, 1.564 s total

| Function                                           |  Cumulative |    Share |
| -------------------------------------------------- | ----------: | -------: |
| `_skill_tags` → `split_skills` / `canonical_skill` |     0.541 s | **35 %** |
| `clean_job_description_text`                       |     0.412 s | **26 %** |
| `_row_text` (+ 28 530 `str.lower` calls)           |     0.349 s | **22 %** |
| `board_facets` (12 leave-one-out passes)           |     0.420 s |   27 % † |
| **SQLAlchemy row fetch (all 18 queries)**          | **0.092 s** |  **6 %** |

† overlaps `_row_text`/`_skill_tags`, which it re-drives per facet.

`re.Pattern.sub` alone accounts for 0.363 s across 64 074 calls. **The database
is not the bottleneck. The projection is.**

### The ceiling — what the same work costs in SQL

| Operation                                               |                       Time |
| ------------------------------------------------------- | -------------------------: |
| Page of 50 + `COUNT(*)`, no `jd_text`                   |                 **2.6 ms** |
| One facet via `GROUP BY`                                | **0.3 ms** (× 11 ≈ 3.3 ms) |
| `q` search via `jd_text LIKE '%python%'` over 2096 rows |                 **3.3 ms** |

**≈ 9 ms against 262–317 ms today — a 30–100× headroom.**

### Payload

| Response                         |        Total | of which `jdText` |  facets |
| -------------------------------- | -----------: | ----------------: | ------: |
| `GET /api/pipeline?pageSize=50`  | **406.8 KB** |      **287.3 KB** | 39.7 KB |
| `GET /api/shortlist?pageSize=50` |     142.6 KB |              0 KB | 29.5 KB |

`PipelineCard.tsx:53` renders that 287 KB inside `line-clamp-3` — **three
clipped lines**. Infinite scroll to the end of the pipeline board is 42
requests ≈ **17 MB transferred and ≈ 12 s of server CPU**.

### Not a problem — measured and cleared, do not "fix" these

- **`load_facts` and `load_aliases` are already `(mtime_ns, size)`-cached.** Leave them.
- **Bundle is within budget.** Initial `index` 275.95 KB (**86.03 KB gzip**) + `lib` 153.77 KB (45.72 KB gzip) ≈ 132 KB gzip, under the 200 KB budget. All 30+ routes are already `lazy()`-split. `AnalyticsPage` is the largest chunk at 345.51 KB (99.50 KB gzip, recharts) but is lazy — acceptable; note it in the budget file, do not refactor it.
- **Test suite is healthy.** Full offline suite green; slowest single test 6.87 s. No dev-loop work needed.
- **React memoisation is adequate.** Module-level constants are hoisted in `FilterDesk.tsx`; `useBoardQuery` memoises flattened rows; search uses a draft-plus-commit input, so there is no per-keystroke refetch. Do not sprinkle `React.memo`.
- **`build_known_index` is 11.2 ms** (1.3 ms with a column projection). Real but small — Phase 5, lowest priority.

---

## Findings, ranked

| #   | Finding                                                                                                                                                                                              | Evidence                                                                                           | Phase |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----- |
| 1   | Board read is **projection-bound, not query-bound**; pagination happens after full materialisation                                                                                                   | last page = first page cost; SQL is 6 % of the profile                                             | 2     |
| 2   | **The composite/preset ranking controls do nothing** — the client sends `preset`, the server has no such parameter and maps `composite` → plain fit-desc                                             | `params.ts:22` sends it; zero `preset` references in `boards.py`/`board.py`; `_sort_rows` line 243 | 1     |
| 3   | **The Filter contract is a seam with no adapters** — its TS half (`lib/filters/apply.ts`, `sort.ts`) is deleted; the Python half is imported only by its own two test files                          | `grep shortlist_filtering src/` → no production hits                                               | 1     |
| 4   | `PipelineItem.jdText` ships **287 KB/page** to render three clipped lines                                                                                                                            | payload table above                                                                                | 3     |
| 5   | **Facets are recomputed on every page and discarded for pages 2+** — the client reads `pages[0].facets` only                                                                                         | `use-board-query.ts:61`; `board_facets` ≈ 140 ms/request                                           | 4     |
| 6   | **JD cleaning runs twice on the same bytes**, implemented twice — `clean_job_description_text` (Python, per row, per request) and `cleanJobDescriptionText` (TS, `lib/format/prettify.ts`, per card) | `PipelineCard.tsx:53`                                                                              | 3     |
| 7   | **The existing benchmark misses the slow board.** `scripts/bench_board.py` covers shortlist + triage — the two boards round 4 already fixed with `defer(jd_text)` — and never benches pipeline       | `scripts/bench_board.py:66`                                                                        | 0     |
| 8   | `build_known_index` / `_prune_rows` hydrate full `Job` entities to build small indexes                                                                                                               | 11.2 ms → 1.3 ms                                                                                   | 5     |

---

## Background for implementers (read once)

1. **Round 4 already did the easy half.** `docs/superpowers/plans/2026-07-19-architecture-deepening-round-4.md` Task 9 added `defer(jd_text)` to `shortlist_rows`, `triage_rows` and `archived_rows` — which is why triage is 1.4 ms. It explicitly scoped out pipeline ("`PipelineItem` and `JobDetail` do [ship jd_text] — their queries must keep loading it") because it had frozen the wire contract. **Phase 3 of this plan reopens exactly that decision.** Round 4's checkboxes are unticked but its work shipped (`sessions/store.py`, `api/runs/launch.py`, `board_filter_query`, `scripts/bench_board.py` all exist).
2. **`BoardFilter`** (`services/board.py:59`) is a frozen dataclass with 24 fields — derive variants with `dataclasses.replace`.
3. **`FACET_SPECS`** (`services/board.py:105`) is the single statement of the
   ordinary facet vocabulary: 11 specs, each `(wire key, row attribute,
   BoardFilter field, skip_unset_rows)`. The twelfth facet, `skills`, has
   split/canonicalized many-to-many semantics and is deliberately handled by a
   dedicated path. Phase 2 moves the read contract and specs into
   `tracking/board_query.py`; `services.board` re-exports `BoardFilter` so
   existing callers do not break. This ownership avoids a
   `services.board -> tracking.board_query -> services.board` import cycle.
4. **Facet values live inside `criteria_json`, not in columns.** `remote_policy`, `seniority`, `industry`, `company_size`, `sponsorship_signal`, `employment_type`, salary and `location_parts.*` are all JSON keys. SQLite supports `json_extract` and SQLAlchemy exposes it as `Job.criteria_json["remote_policy"].as_string()`. This is the crux of Phase 2 — read Task 5 before starting it.
5. **`company_size` is snapped in Python** by `taxonomy.company_size.snap`
   before it reaches the wire. A raw `json_extract` will **not** match the
   snapped value. Task 5 Step 4 queries the finite set of raw values present in
   the database, snaps those values in Python, then uses the matching raw set in
   SQL. It must not try to enumerate all theoretically possible raw strings.
6. **Leave-one-out faceting is a deliberate feature**, not an accident — choosing one value must not zero out its siblings (commit `b0a1c965`). `GROUP BY` preserves this naturally: build the facet's count query with every filter _except_ its own. Do not regress it; `tests/api/test_board_facets.py` guards it.
7. **The `q` filter searches the fields present on each current row DTO.**
   Pipeline rows include `status` and `jd_text`; triage rows include `status`
   but not `jd_text`; shortlist rows include neither. Moving `q` to SQL must
   preserve that board-specific surface and literal substring semantics:
   escape SQL wildcard characters (`%` and `_`) rather than interpreting user
   input as a pattern. SQLite `LIKE` is case-insensitive for ASCII by default;
   Task 5 pins ASCII case-folding and wildcard literals with tests.
8. **Row DTOs are the API projection surface.** `ShortlistItem.model_validate(row)` whitelists fields off the richer DTO. Column projections must therefore keep every attribute the schema names, or validation fails at runtime rather than at type-check time.

---

# Phase 0 — extend the benchmark to the board that is actually slow

### Task 1: `scripts/bench_board.py` covers pipeline, payload size, and page depth

**Files:**

- Modify: `scripts/bench_board.py`
- Create: `docs/notes/2026-07-24-board-baseline.md`
- Create: `tests/scripts/test_bench_board.py`

**Interfaces:**

- Produces (used by every later phase): a repeatable `--board pipeline` benchmark and a recorded baseline table.

- [ ] **Step 1: Write the failing benchmark behavior test**

Pin that the seed creates non-empty pipeline data with production-shaped
`criteria_json`, that an explicit page is honored, and that the rendered report
contains total / `jdText` / facet byte counts.

- [ ] **Step 2: Seed realistic pipeline rows**

The current `seed()` writes only `shortlisted` / `raw`. The pipeline board reads
all active statuses, so those rows are visible, but the seed does not exercise
real pipeline status diversity or legacy stage ordering. Widen it to cycle
`("shortlisted", "raw", "approved", "tailored", "rendered", "rejected")` and
grow `jd_text` to ~5.6 KB to match the measured production average.
Use the real JSON keys: `salary_range.minimum` / `maximum`,
`must_have_skills`, `nice_to_have_skills`, `tech_stack`, and the ordinary
facet keys. The existing benchmark's `salary_range.min` / `max` and
`hard_skills` do not exercise production projections.

- [ ] **Step 3: Add `--board` and `--page`**

Add `pipeline` to the default board loop, a `--board` selector, and a `--page`
selector accepting positive page numbers plus `last`. Later plan commands
already use `--board pipeline`; this option is part of the interface, not an
out-of-band assumption.

- [ ] **Step 4: Report response payload bytes alongside latency**

After timing, project the page through `to_board_page(...)` with the matching schema and print `model_dump_json(by_alias=True)` length, split into total / `jdText` / facets. Latency alone would not have surfaced finding #4.
Measure UTF-8 bytes (`len(json_text.encode("utf-8"))`), not Python character
count.

- [ ] **Step 5: Record the baseline**

Run `--rows 2000 --repeat 10 --page 1 last` for all three boards and write the
table into `docs/notes/2026-07-24-board-baseline.md` together with the production
numbers from this plan's Baseline section.

- [ ] **Step 6: Verify and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/scripts/test_bench_board.py -v
.venv/Scripts/python.exe scripts/bench_board.py --rows 2000 --repeat 10 --page 1 last
ruff check scripts/bench_board.py tests/scripts/test_bench_board.py
git add scripts/bench_board.py tests/scripts/test_bench_board.py docs/notes/2026-07-24-board-baseline.md
git commit -m "bench(board): cover the pipeline board, page depth, and payload size"
```

**Gate:** every later performance task is measured against this file. A task that does not move its numbers gets reverted, not kept.

---

# Phase 1 — delete the seam with no adapters, and fix what it was hiding

> **Do this before Phase 2.** Phase 2 must implement `composite` in SQL, and it
> cannot do that until we decide what `composite` means.

### Task 2: Confirm and record the dead Filter contract

**Files:**

- Read: `src/resume_agent/services/shortlist_filtering.py`, `contracts/shortlist_filter.contract.json`, `tests/test_shortlist_filtering.py`, `tests/test_shortlist_filter_contract.py`, `web/src/lib/filters/`

- [ ] **Step 1: Re-verify the deletion test before deleting anything**

```bash
grep -rn "shortlist_filtering" src/ web/src/     # expect: no hits at all
grep -rn "shortlist_filtering" tests/            # expect: only the two test files
ls web/src/lib/filters/                          # expect: no apply.ts, no sort.ts
```

`web/src/lib/filters/` retains only `params.ts`, `normalize.ts`, `types.ts`,
`industry-label.ts` and their tests. The **Conformance harness** described in
CONTEXT.md has one runtime left, and that runtime's only caller is its own test.
**One adapter is a hypothetical seam; zero adapters is dead weight.**

If any of those greps contradicts this, **stop and report** — the rest of Phase 1 is invalid.

- [ ] **Step 2: Extract the one thing worth keeping**

Before deleting, copy out `PRESETS` (`balanced` `(0.50, 0.30, 0.20)`, `pay_first` `(0.30, 0.55, 0.15)`, `freshest` `(0.35, 0.20, 0.45)`), `SALARY_CEILING = 250_000`, `RECENCY_WINDOW_DAYS = 30`, `NEUTRAL = 50.0` and the `composite_score` formula into the task-3 scratch notes. These weights are the **only** surviving statement of what "composite" means.

### Task 3: Composite rank and presets become real again (**behaviour change**)

**Files:**

- Modify: `src/resume_agent/services/board.py`, `src/resume_agent/api/routers/boards.py`
- Create: `tests/api/test_board_composite_rank.py`

**Interfaces:**

- Produces: `Preset` and `SortKey` literal types;
  `BoardFilter.preset: Preset = "balanced"`; `_sort_rows` handling `composite`
  as a genuine weighted rank.
- Consumed by: Phase 2 Task 5 (which must express this sort in SQL).

> **Decision (settled 2026-07-24): revive the ranking server-side.** The UI
> already ships the control and the weights are recoverable, so the fix is to
> teach the server the parameter it never learned — not to delete a shipped
> affordance. The rejected alternative was removing the preset selector and the
> `composite` sort option from `FilterDesk.tsx` / `types.ts` and dropping
> `preset` from `boardFilterToParams`; it was cheaper but lost the feature and
> the weights with it. Task 5 Step 5 must therefore express this rank in SQL.
>
> **Extraction is load-bearing:** Task 2 Step 2 is the _only_ opportunity to
> recover `PRESETS`, `SALARY_CEILING`, `RECENCY_WINDOW_DAYS` and
> `composite_score` before Task 4 deletes `shortlist_filtering.py`. Do not
> reorder Task 4 ahead of Task 3.

- [ ] **Step 1: Write the failing test first**

`tests/api/test_board_composite_rank.py` — seed three jobs where fit, salary and
recency disagree on the ordering, then assert that
`sortBy=composite&preset=pay_first` and `sortBy=composite&preset=freshest` return
**different** orders, and that both differ from `sortBy=fit`. Run it; watch all
three assertions fail identically today (every ordering collapses to fit-desc).
That failure **is** the regression, reproduced.
Also assert an unknown `preset` and unknown `sortBy` are rejected with 422
rather than reaching a dictionary lookup or silently returning database order.

- [ ] **Step 2: Add `preset` to the query surface**

In `board_filter_query`, add
`preset: Literal["balanced", "pay_first", "freshest"] = Query("balanced")`
and type `sortBy` as the accepted sort literal (including legacy `stage`).
Pass both into `BoardFilter`. FastAPI silently drops unknown query parameters,
which is exactly why the client has been sending `preset` into the void.

- [ ] **Step 3: Implement the weighted rank**

Port `composite_score` from the extracted notes into `services/board.py` as a
module-level pure function over a row: normalise `fit_score` to 0–100 (missing →
`NEUTRAL`), salary against `SALARY_CEILING`, and recency against
`RECENCY_WINDOW_DAYS`; combine with the `PRESETS` weights. Sort at full
precision — rounding is display-only and must never enter the ordering. Route
`_sort_rows`' `"composite"` branch to it; leave `"fit"` on `_by_fit_desc`.

- [ ] **Step 4: Verify and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_board_composite_rank.py -v
.venv/Scripts/python.exe scripts/export_openapi.py
npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item contracts/ts/api.ts web/src/lib/api/schema.ts
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v
ruff check src/resume_agent/services/board.py src/resume_agent/api/routers/boards.py tests/api/test_board_composite_rank.py
git add src/resume_agent/services/board.py src/resume_agent/api/routers/boards.py tests/api/test_board_composite_rank.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "fix(board): composite sort and presets reach the server again"
```

`contracts/openapi.json` **does** gain a `preset` query parameter here. This is
the one Phase-1 contract change; regenerate and commit it in the same commit,
and confirm `tests/api/test_openapi_contract.py` passes.

### Task 4: Delete the dead contract and its harness

**Files:**

- Delete: `src/resume_agent/services/shortlist_filtering.py`, `contracts/shortlist_filter.contract.json`, `tests/test_shortlist_filtering.py`, `tests/test_shortlist_filter_contract.py`
- Modify: `contracts/README.md`

- [ ] **Step 1: Delete, then prove nothing moved**

Remove the four files, drop the contract's entry from `contracts/README.md`, then
run the focused board slice now and the full suite at the final gate.
**253 lines of tests disappear and no other test changes** — that is the
deletion test passing: complexity vanished rather than relocating.

- [ ] **Step 2: Verify and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_board_composite_rank.py tests/test_services_board.py -q
ruff check src tests
git rm src/resume_agent/services/shortlist_filtering.py contracts/shortlist_filter.contract.json tests/test_shortlist_filtering.py tests/test_shortlist_filter_contract.py
git add contracts/README.md
git commit -m "chore(filters): delete the cross-language filter contract; its TS half is gone"
```

CONTEXT.md still defines **Filter contract**, **Conformance harness** and
**Composite rank**. Phase 6 Task 11 rewrites those three entries — do not touch
CONTEXT.md here.

---

# Phase 2 — the Board seam becomes a real query

> The deepening. Today `services/board.py` materialises every row, then
> reimplements `WHERE`/`ORDER BY`/`LIMIT`/`GROUP BY` in Python over `list[Any]`
> with `getattr` lookups. After this phase, one statement builder is the single
> author of board selection, and rows are built only for the page returned.

### Task 5: `tracking/board_query.py` — one statement builder

**Files:**

- Create: `src/resume_agent/tracking/board_query.py`, `tests/tracking/test_board_query.py`
- Modify: `src/resume_agent/services/board.py` (compatibility re-exports only)

**Interfaces:**

- Produces:
  - `board_statement(session, board, f, *, now, aliases_path) -> Select` —
    filtered + sorted, no limit
  - `board_page(session, board, f, *, page, page_size, now, aliases_path) -> tuple[list[Job], int]`
  - `board_facet_counts(session, board, f, *, now, aliases_path) -> Facets`
- Consumed by: Task 6.

- [ ] **Step 1: Move the read contract without creating an import cycle**

Move `BoardName`, `SortKey`, `Preset`, `BoardFilter`, `FacetSpec`, and
`FACET_SPECS` into `tracking/board_query.py`; import/re-export the public names
from `services.board` for compatibility. Add a fourth field,
`sql: Callable[[], ColumnElement]`, to `FacetSpec`. Column-backed facets return the column
(`source`, `status`); JSON-backed facets return
`Job.criteria_json["remote_policy"].as_string()` and friends per background note 4. `FACET_SPECS` stays **the single statement of the facet vocabulary** — the
new column is the SQL half of a fact already declared there, not a second table.
Do not import `services.board` from `tracking.board_query`.

- [ ] **Step 2: Write the equivalence tests first**

`tests/tracking/test_board_query.py` seeds ~200 jobs spanning every facet value,
then for a table of ~15 representative `BoardFilter` instances asserts that
`board_page(...)` returns **exactly the same ordered job ids** as today's
`_sort_rows(_apply_board_filter(_raw_board_rows(...)))`. Include: empty filter;
each facet alone; two facets combined; `q`; `min_fit`/`max_fit`; `min_salary`;
`stale_days`; `stale_min_days`; each `sort` value; `composite` × each preset.
Include literal `%` and `_` search terms, missing values, compound/aliased
skills, snapped free-text company sizes, and ties spanning a page boundary.
Pin the board-specific search surface: only pipeline searches `jd_text`;
shortlist does not search `status`; triage searches `status` but not `jd_text`.

This table **is** the safety net for the whole phase. Write it before any
builder code, and keep the old Python path importable until Task 6 deletes it,
so both sides can be compared directly.

- [ ] **Step 3: Build the statement**

Translate `_passes_filter` clause-for-clause into SQLAlchemy: the base
per-board `WHERE` (status set + `archived_at`), then `q` → `LIKE` across
company/title/location/source/status/`jd_text`, `reject_reason` → `LIKE`, the
fit range, `min_salary` (guarding `currency == 'USD'` as today), the two
staleness windows, then one `IN` per selected facet — honouring
`skip_unset_rows` with `OR <expr> IS NULL` for `industry`.
Use escaped contains semantics for user strings. Capture one `now` in
`list_board` and pass it through page and facet statements so rows, totals, and
facets cannot disagree at a staleness/recency boundary.

- [ ] **Step 4: Handle the two values that are computed, not stored**

`company_size` is snapped by `taxonomy.company_size.snap` and `skills` are
split-and-canonicalised — neither round-trips through a raw `json_extract`.
Invert them at the **filter** interface rather than the row implementation.
For company size, query the distinct raw values actually present, snap them in
Python, and use the matching raw values in an SQL `IN`. For skills, query the
distinct raw entries from `json_each` across `must_have_skills`,
`nice_to_have_skills`, and `tech_stack`; split and canonicalize those entries in
Python, then use exact raw-entry membership in SQL `EXISTS` clauses. Prove both
with dedicated cases in the Step-2 table. **Never apply a Python skill
post-filter after `LIMIT`/`OFFSET`**: it would make totals wrong and could drop
matching rows from a page.

- [ ] **Step 5: Sorting and paging**

`fit` → `fit_score DESC NULLS LAST`; `salary` → `COALESCE(max, min, 0) DESC`;
`recency` → `posted_at DESC NULLS LAST`; `company` → `lower(company), lower(title)`;
legacy `stage` → `status, lower(company)`; `composite` → the Task-3 weighted expression
in SQL. Add a stable `Job.id` tiebreak to every ordering so pagination cannot
drop or repeat a row between pages. `board_page` returns
`(rows, total)` using `LIMIT`/`OFFSET` plus one `SELECT COUNT(*)` over the same
`WHERE`.

- [ ] **Step 6: Facet counts by GROUP BY**

`board_facet_counts` runs one `GROUP BY` per ordinary spec, each with the
leave-one-out `WHERE` (background note 6) — every filter except that facet's
own. The twelfth `skills` facet uses one projected `job_id` + raw-skill query
and canonicalizes/deduplicates per job in Python, preserving `_skill_tags`
semantics without hydrating jobs or descriptions. Company-size raw groups are
snapped and merged before returning counts.

- [ ] **Step 7: Verify and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/tracking/test_board_query.py -v
ruff check src/resume_agent/tracking/board_query.py src/resume_agent/services/board.py tests/tracking/test_board_query.py
git add src/resume_agent/tracking/board_query.py src/resume_agent/services/board.py tests/tracking/test_board_query.py
git commit -m "feat(board): one SQL statement builder for board filter, sort, page, and facets"
```

### Task 6: `list_board` projects only the page

**Files:**

- Modify: `src/resume_agent/services/board.py`, `src/resume_agent/services/pagination.py`, `src/resume_agent/tracking/queries.py`
- Modify: `tests/test_services_pagination.py`

- [ ] **Step 1: Rewrite `list_board` on the builder**

```
page_jobs, total = board_query.board_page(session, board, f, page=page, page_size=page_size)
facets          = board_query.board_facet_counts(session, board, f)
rows            = [project(job) for job in page_jobs]   # <= page_size rows, not 2096
```

`_raw_board_rows` disappears from the read path. The current `paginate()` always
slices its input and derives `total` from `len(items)`, so passing a page into it
would empty page 2 and report the wrong total. Add a tested
`page_from_slice(items, total=..., page=..., page_size=...)` constructor in
`services.pagination`; use that for SQL-paged results while keeping `Page`
ownership in the pagination module.

- [ ] **Step 2: Make the row projections page-scoped**

Split each of `shortlist_rows` / `pipeline_rows` / `triage_rows` into its query
half (now owned by `board_query`) and its projection half — `_shortlist_row`,
`_triage_row` and the pipeline row builder — taking an explicit job list. Keep
the whole-board functions as thin wrappers for the CLI and existing callers so
their tests keep passing.

The per-row batch lookups in `pipeline_rows` (`versions_by_job`,
`applications_by_job`, `progressed_job_ids`) must now be scoped to the page's
job ids — otherwise the fix trades a full row scan for a full join scan.

- [ ] **Step 3: Delete the superseded Python query engine**

Remove `_apply_board_filter`, `_passes_filter`, `_row_text`, `_row_skill_tokens`,
`_count_values`, `_count_skills`, `board_facets`, `_sort_rows`,
`_posted_sort_value`, `_salary_sort_value`, `_by_fit_desc` and `_board_rows` —
roughly 150 lines of `getattr`-over-`Any` reimplementation of SQL. Keep
`_normalize_token` if Task 5 Step 4 fell back to a Python skills post-filter.

- [ ] **Step 4: Verify against the baseline**

```bash
.venv/Scripts/python.exe -m pytest tests/tracking/test_board_query.py tests/test_services_board.py tests/test_services_pagination.py -v
ruff check src/resume_agent/services/board.py src/resume_agent/services/pagination.py src/resume_agent/tracking/queries.py
.venv/Scripts/python.exe scripts/bench_board.py --rows 2000 --repeat 10
```

**Threshold:** pipeline page 1 must drop below **50 ms** (from 261.6 ms) and
page 40 must be within 20 % of page 1 (from parity at 219.2 ms). If the
threshold is not met, profile before adding anything further — do not guess.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/board.py src/resume_agent/services/pagination.py src/resume_agent/tracking/queries.py tests/test_services_pagination.py
git commit -m "perf(board): filter, sort, and page in SQL; project only the returned page"
```

---

# Phase 3 — stop shipping 287 KB to render three lines (**contract change**)

### Task 7: `PipelineItem.jdText` becomes a server-rendered `jdPreview`

**Files:**

- Modify: `src/resume_agent/api/schemas/jobs.py`, `src/resume_agent/tracking/queries.py`, `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/features/pipeline/PipelineCard.tsx`
- Create: `tests/api/test_pipeline_payload.py`

**Interfaces:**

- Produces: `PipelineItem.jd_preview: str` (≤ 400 chars, already cleaned) replacing `jd_text`.
- `JobDetail.jd_text` is **unchanged** — the modal genuinely needs the full text.

- [ ] **Step 1: Write the payload budget test first**

`tests/api/test_pipeline_payload.py` seeds 50 jobs with 6 KB descriptions and
asserts the serialised `GET /api/pipeline?pageSize=50` body is **under 150 KB**.
Run it and watch it fail at ~407 KB. Keep this test — it is the regression
guard that stops the field growing back.

- [ ] **Step 2: Replace the field**

Rename `jd_text` → `jd_preview` on `PipelineItem`, and in the pipeline row
builder emit `clean_job_description_text(job.jd_text)[:400]`. The page query
still loads source `jd_text` for the at-most-`pageSize` jobs needed to compute
that preview; it must not defer the field and trigger N+1 lazy loads. The gain
is that the full table is no longer hydrated and the full text never crosses
the wire. Persisting a preview column is out of scope. The `q` filter still
searches `jd_text` in SQL.

- [ ] **Step 3: Delete the duplicated client-side cleaner**

`PipelineCard.tsx:53` calls `cleanJobDescriptionText(row.jdText)` — the client
re-cleaning bytes the server already cleaned. Render `{row.jdPreview}` directly.
Keep `cleanJobDescriptionText` in `web/src/lib/format/prettify.ts`:
`prettifyPlainText` still uses it for the full `JobDetail` display. This task
removes the duplicate board-path invocation, not the detail formatter.

- [ ] **Step 4: Regenerate the contract**

```bash
.venv/Scripts/python.exe scripts/export_openapi.py
npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item contracts/ts/api.ts web/src/lib/api/schema.ts
cd web && npm run test:run -- PipelineContainer && cd ..
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v
```

- [ ] **Step 5: Verify and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_pipeline_payload.py tests/api/test_openapi_contract.py -v
ruff check src/resume_agent/api/schemas/jobs.py src/resume_agent/tracking/queries.py tests/api/test_pipeline_payload.py
.venv/Scripts/python.exe scripts/bench_board.py --rows 2000 --repeat 10 --board pipeline
git add src/resume_agent/api/schemas/jobs.py src/resume_agent/tracking/queries.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts web/src/features/pipeline/PipelineCard.tsx tests/api/test_pipeline_payload.py
git commit -m "perf(pipeline)!: ship a 400-char jdPreview instead of the full description"
```

**Threshold:** pipeline page payload under **150 KB** (from 406.8 KB). The
measured non-JD response is already ~119.5 KB; adding up to 20 KB of preview
text makes the original 120 KB raw-body target arithmetically impossible.

---

# Phase 4 — compute facets once per filter, not once per page

### Task 8: Facets ride the first page only

**Files:**

- Modify: `src/resume_agent/api/routers/boards.py`, `src/resume_agent/services/board.py`
- Create: `tests/api/test_board_facet_paging.py`

The client reads `pages?.[0]?.facets` (`use-board-query.ts:61`) and discards the
rest. The server computes them 42 times for a full pipeline scroll.

- [ ] **Step 1: Test first**

Assert `GET /api/pipeline?page=1` carries a populated `facets` object and
`?page=2` carries `null`, while `data` and `pagination` are unaffected on both.

- [ ] **Step 2: Skip facet computation when `page > 1`**

Pass `page` into `list_board`'s facet step and return `None` for later pages.
The handwritten hook type already treats facets as optional, but the Pydantic
schema currently requires a dictionary. Change it to `Facets | None` and
regenerate all three generated contract artifacts in this commit.

- [ ] **Step 3: Verify and commit**

```bash
.venv/Scripts/python.exe scripts/export_openapi.py
npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item contracts/ts/api.ts web/src/lib/api/schema.ts
.venv/Scripts/python.exe -m pytest tests/api/test_board_facet_paging.py tests/api/test_openapi_contract.py -v
ruff check src/resume_agent/api/routers/boards.py src/resume_agent/services/board.py tests/api/test_board_facet_paging.py
git add src/resume_agent/api/schemas/base.py src/resume_agent/api/mappers.py src/resume_agent/api/routers/boards.py src/resume_agent/services/board.py tests/api/test_board_facet_paging.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "perf(board): compute facets on the first page only"
```

_After Phase 2 this saves ~3 ms per subsequent page rather than ~140 ms — worth
doing for the wasted 30–40 KB of repeated facet JSON per page, but **do not run
this phase before Phase 2**, where it would merely paper over the real cost._

---

# Phase 5 — small, measured wins

### Task 9: Index builders select columns, not entities

**Files:**

- Modify: `src/resume_agent/discovery/known_jobs.py`, `src/resume_agent/tracking/repository.py`
- Create: `tests/tracking/test_query_projections.py`

- [ ] **Step 1: Write the failing hydration test**

Use SQLAlchemy's entity-load event in a fresh session to prove
`build_known_index` and `_prune_rows` do not hydrate any `Job` entities. This
pins the performance behavior without asserting a brittle SQL string.

- [ ] **Step 2: Project columns in `build_known_index`**

`build_known_index` hydrates full `Job` entities — including `jd_text` — to read
four fields (`source`, `url`, `dedup_key`, `location`). Select those columns.
Measured: **11.2 ms → 1.3 ms.**

- [ ] **Step 3: Same for `_prune_rows`**

`repository.py:483` does `select(Job)` to build a six-field row per job. Project
those columns.

- [ ] **Step 4: Verify and commit**

```bash
.venv/Scripts/python.exe -m pytest tests/tracking/test_query_projections.py tests/test_discovery_ingest.py tests/test_prune.py -v
ruff check src/resume_agent/discovery/known_jobs.py src/resume_agent/tracking/repository.py tests/tracking/test_query_projections.py
git add src/resume_agent/discovery/known_jobs.py src/resume_agent/tracking/repository.py tests/tracking/test_query_projections.py
git commit -m "perf(discovery,prune): project columns instead of hydrating full Job rows"
```

### Task 10: Record the frontend performance budget

**Files:**

- Create: `web/performance-budget.md`

- [ ] **Step 1: Write down the measured budget**

Initial JS ≤ 200 KB gzip (currently ≈ 132 KB: `index` 86.03 + `lib` 45.72);
largest lazy route chunk ≤ 120 KB gzip (currently `AnalyticsPage` 99.50 KB);
board page response ≤ 150 KB (Phase 3). Note that all routes are already
`lazy()`-split and that no bundle work is warranted at these numbers — this file
exists so a future regression is visible, not to justify a refactor now.

- [ ] **Step 2: Commit**

```bash
git add web/performance-budget.md
git commit -m "docs(web): record the measured frontend performance budget"
```

---

# Phase 6 — bring the documentation back to the truth

### Task 11: CONTEXT.md, CLAUDE.md, and an ADR for the board query

**Files:**

- Modify: `CONTEXT.md`, `CLAUDE.md`
- Create: `docs/adr/0007-board-filtering-in-sql.md`

- [ ] **Step 1: Remove three now-false CONTEXT.md terms**

Delete **Filter contract** and **Conformance harness** (Task 4 deleted both
halves). Rewrite **Composite rank** to describe the server-side weighted sort
from Task 3 — dropping the "Python and JS order identically" clause, which
stopped being true when the JS half was deleted.

- [ ] **Step 2: Correct the Board seam entry**

Its current claim — _"Raw list projections stay in `tracking.queries` and are
called directly by both adapters — wrapping them in board would add shallow
pass-throughs and fight the frontend's rich in-process filtering"_ — is now
false in both halves: the frontend does **not** filter in process (it sends
filter state as query parameters via `boardFilterToParams`), and the projections
no longer own selection. Rewrite it around `board_query` as the single author of
board selection.

- [ ] **Step 3: Add two terms**

**Board query** (`tracking/board_query.py`) — the single statement builder that
turns a `BoardFilter` into filtered, sorted, paged SQL plus its leave-one-out
`GROUP BY` facet counts; the only place board selection is expressed.
**JD preview** — the ≤ 400-char cleaned excerpt boards ship in place of the full
description; the full text lives on `JobDetail` alone.

- [ ] **Step 4: Write ADR-0007**

Record: boards filter in SQL, not in Python over materialised rows. Context —
the measured 262 ms / 6 %-SQL profile in this plan. Decision — `board_query`
owns selection; row projections build only the returned page. Consequences —
facet values that are computed rather than stored (`company_size`, `skills`)
must be inverted at the filter boundary (Task 5 Step 4); adding a facet now
means adding a SQL expression to `FACET_SPECS`, not a Python predicate. Add it
to `docs/adr/README.md`.

- [ ] **Step 5: Sync CLAUDE.md**

Update the "Board filters are declared once" bullet to name `board_query`, and
add a note under Known design notes: **boards page in SQL; only the returned
page is projected; `PipelineItem` ships `jdPreview`, and full `jd_text` is
`JobDetail`-only.**

- [ ] **Step 6: Verify and commit**

```bash
git diff --check
git add CONTEXT.md CLAUDE.md docs/adr/0007-board-filtering-in-sql.md docs/adr/README.md
git commit -m "docs: record the board query seam; drop the deleted filter contract terms"
```

---

## Final verification checklist

- [ ] `.venv/Scripts/python.exe -m pytest` — green
- [ ] `make verify` — Python/API gate, web tests, both linters, and web build green
- [ ] `ruff check src tests evals` — clean
- [ ] `cd web && npm run test:run` — green
- [ ] `cd web && npm run lint && npm run build` — green
- [ ] `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py` — green (contract regenerated in Phases 1, 3 and 4 only)
- [ ] `scripts/bench_board.py --rows 2000 --repeat 10`: pipeline page 1 **< 50 ms** (was 261.6 ms); page 40 within 20 % of page 1 (was equal)
- [ ] Pipeline page payload **< 150 KB** (was 406.8 KB)
- [ ] `grep -rn "shortlist_filtering" src/ tests/ web/src/` — no hits
- [ ] Manual check in the running app: the **Composite** sort and the three presets produce visibly different orderings
- [ ] `docs/notes/2026-07-24-board-baseline.md` updated with before/after
- [ ] Five-axis self-review (correctness, readability, architecture, security,
      performance), scoped simplification pass, `git diff --check`, then rerun
      the checks affected by any refactor

## Explicitly out of scope

- Bundle splitting or `AnalyticsPage`/recharts work — measured, within budget (Task 10 records it).
- Caching `load_facts` / `load_aliases` — already `(mtime_ns, size)`-cached.
- Test-suite speed — healthy; slowest test 6.87 s.
- New indexes on `jobs` — SQL is 6 % of the request; revisit only if the Task 6 threshold is missed and profiling indicts a scan.
- `cli.py` (1239 lines) — large, but it is 30 genuinely distinct Typer commands over the `services/` layer, not duplicated logic. Splitting it is cosmetic; not proposed.
