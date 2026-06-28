# Match / Gap Dashboard Redesign Implementation Plan

> **Design:** `docs/superpowers/specs/2026-06-27-match-gap-dashboard-redesign-design.md`
> **Reviewed:** 2026-06-27
> **Method:** contract-first, test-driven, one independently green commit per task

## Goal

Deliver a theme-first Match/Gap workspace with stable generalized-skill
identity, one consistent dashboard snapshot, bounded suggestion runs, an
accessible constellation map, a dense ranked outline, a large skill modal, and
multi-target generation.

## Architecture

- Deepen `tracking.match_gap`: normalization, canonical identity, display-label
  selection, counting, edges, and theme aggregates stay behind one interface.
- Extend `GET /api/match-gap` with persisted suggestion status. Do not add a
  second unpaginated status-list interface.
- Put all suggestion run construction behind one submission module used by the
  legacy single route and the new multi-target route.
- Deepen `RunManager` with a managed executor lane per run kind. Do not resize
  the shared executor and do not occupy shared workers waiting on semaphores.
- Keep server data in TanStack Query, transient suggestion-run state in one
  feature-local registry, and view/filter/selection state in the container.
- Use the installed Base UI shadcn primitives and semantic theme tokens.
- Compute force layout off-DOM from cloned inputs; render accessible HTML node
  controls over SVG links.

## Non-negotiable interfaces

### Stable identity

- Skill `key` is canonical and stable.
- Skill `skill` is a display label retained for backward compatibility.
- Edge `skillKey` is canonical; edge `skill` remains the display label.
- Selection, suggestion cache, graph node IDs, and React keys use `key`.
- No colon-delimited string parsing for typed targets.

### Wire format

- Python fields are snake_case; `CamelModel` emits camelCase.
- Existing fields remain; all graph changes are additive.
- Batch request: `POST /api/suggestion-runs` with 1–25 `targets`.
- Batch response: ordered discriminated `results` with `outcome` equal to
  `accepted` or `not_found`.
- Every input/output model forbids unrecognized request fields where applicable.
- Regenerate `contracts/openapi.json` and `contracts/ts/api.ts`; never hand-edit
  generated files.

### Counting

- Member phrasing count = distinct jobs containing that exact trimmed phrasing.
- Source count = distinct jobs containing the canonical skill in that source.
- Skill job count = distinct jobs across all sources.
- Theme `jobCount` = distinct union of jobs across member skills.
- Filtered UI values always derive from filtered edges, not server baselines.

### UI and accessibility

- Base UI composition uses `render`, not `asChild`.
- `TabsTrigger` lives in `TabsList`; dialog/sheet always has title and
  description; select items live in `SelectGroup`.
- Checkbox and row/detail actions are siblings; no nested interactive controls.
- Buttons use Lucide icons with `data-icon`; status uses `Badge` plus text.
- Loading uses `Skeleton`, errors use `Alert`, and empty states use `Empty`.
- Test 320, 768, 1024, and 1440 px; honor reduced motion.

## File map

### Backend and contract

- Modify `src/resume_agent/tracking/match_gap.py`
- Modify `src/resume_agent/services/suggestions.py`
- Create `src/resume_agent/services/suggestion_runs.py`
- Modify `src/resume_agent/api/runs/manager.py`
- Modify `src/resume_agent/api/schemas/match_gap.py`
- Modify `src/resume_agent/api/schemas/suggestions.py`
- Modify `src/resume_agent/api/routers/match_gap.py`
- Modify `src/resume_agent/api/routers/suggestions.py`
- Modify `src/resume_agent/api/app.py`
- Modify `src/resume_agent/config.py`
- Regenerate `contracts/openapi.json`, `contracts/ts/api.ts`
- Modify tests under `tests/` and `tests/api/`

### Frontend

- Modify `web/src/index.css`
- Modify `web/src/lib/runs/store.ts`, `web/src/lib/runs/sse.ts`
- Modify `web/src/features/match-gap/aggregate.ts`
- Rewrite `web/src/features/match-gap/MatchGapContainer.tsx`
- Rewrite `web/src/features/match-gap/RankedList.tsx`
- Modify `web/src/features/match-gap/Filters.tsx`
- Create `web/src/features/match-gap/suggestion-run-registry.ts`
- Create `web/src/features/match-gap/use-suggestion-runs.ts`
- Create `web/src/features/match-gap/skill-map-layout.ts`
- Create `web/src/features/match-gap/SkillMap.tsx`
- Create `web/src/features/match-gap/SkillModal.tsx`
- Create `web/src/features/match-gap/SelectionTray.tsx`
- Delete `WordCloud.tsx`, `StatTables.tsx`, `SkillDrawer.tsx` and superseded tests
- Modify `web/package.json`, `web/package-lock.json`

---

## Task 1 — Stable demand-graph identity and aggregation

**Files:**

- Modify `src/resume_agent/tracking/match_gap.py`
- Modify `tests/test_tracking_match_gap.py`
- Modify `tests/test_demand_graph.py` only if its public-interface fixtures need
  the additive fields

### Step 1: Add failing invariant tests

Cover all of these independently:

1. Aliases `python3` and `python` produce one node with `key == "python"`.
2. Reversing job and skill input order does not change node/edge/theme output.
3. Highest-frequency display wins; equal frequency uses ascending casefold then
   original-string order.
4. Repeating `Python` twice in one job counts one member occurrence.
5. One job listing the skill in `must` and `tech` increments both source counts
   but only one `job_count`.
6. Edges carry stable `skill_key` and final display `skill` without a second job
   traversal.
7. Theme essential/popular/job/skill/gap aggregates obey the design.
8. Unclustered skills remain nodes and make `clusters_stale` true.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_tracking_match_gap.py tests/test_demand_graph.py -v
```

Expected: new tests fail because stable keys and aggregates do not exist.

### Step 2: Implement one-pass canonical accumulation

- Add `key`, `members`, source counts, and `job_count` to `SkillNode`.
- Add `skill_key` to `DemandEdge`.
- Add named unfiltered aggregates to `ThemeNode`; do not expose one ambiguous
  `score` field.
- Accumulate internal edges by canonical key during the existing target-job
  traversal.
- Select labels after accumulation and project display strings into nodes/edges
  without traversing jobs again.
- Sort nodes, members, edges, and themes deterministically at the interface.

Apply the deletion test to helper modules: keep counting helpers private unless
deleting one would spread a rule across callers. The public test surface is
`build_demand_graph`.

### Step 3: Verify

```powershell
.venv/Scripts/python.exe -m pytest tests/test_tracking_match_gap.py tests/test_demand_graph.py -v
.venv/Scripts/ruff.exe check src/resume_agent/tracking/match_gap.py tests/test_tracking_match_gap.py tests/test_demand_graph.py
```

Commit: `feat(match-gap): add stable skill identity and graph aggregates`

---

## Task 2 — Dashboard snapshot and legacy suggestion-key compatibility

**Files:**

- Modify `src/resume_agent/api/schemas/match_gap.py`
- Modify `src/resume_agent/services/suggestions.py`
- Modify `src/resume_agent/api/routers/match_gap.py`
- Modify `tests/api/test_schemas_match_gap.py`
- Modify `tests/api/test_match_gap.py`
- Modify `tests/test_services_suggestions.py`

### Step 1: Define and test the contract first

Extend schemas with:

- `SkillNodeOut.key`, `members`, `must`, `nice`, `tech`, `jobCount`.
- `DemandEdgeOut.skillKey`.
- `ThemeOut.essentialScore`, `popularScore`, `jobCount`, `skillCount`,
  `gapCount`.
- `SuggestionStatusOut{kind,key,state,generatedAt}`.
- `MatchGapOut.suggestionStatuses` with `Field(default_factory=list)` for
  compatibility.

Schema tests assert camelCase serialization and exact enum values.

### Step 2: Add failing snapshot tests

Test:

- no persisted rows returns `suggestionStatuses: []`;
- current fingerprint returns `ready`;
- changed demand/profile fingerprint returns `stale`;
- disappeared targets are omitted;
- status keys are canonical even when the persisted row uses a current display
  label;
- a display-label frequency change keeps the same canonical target and reports
  stale instead of dropping the row;
- canonical row wins when canonical and legacy rows both exist;
- `GET /api/match-gap` calls `build_demand_graph` once.

### Step 3: Deepen the suggestion catalog implementation

Add focused functions in `services/suggestions.py` for:

- resolving a skill by canonical key with display-label fallback;
- selecting the canonical/legacy persisted row deterministically;
- deriving all statuses from one already-built graph and profile coverage;
- reusing a legacy row and rewriting its key on successful regeneration.

The match-gap router builds the graph once and passes it to the catalog. It does
not issue N calls through the single-suggestion HTTP interface.

### Step 4: Verify

```powershell
.venv/Scripts/python.exe -m pytest tests/test_services_suggestions.py tests/api/test_schemas_match_gap.py tests/api/test_match_gap.py -v
.venv/Scripts/ruff.exe check src/resume_agent/services/suggestions.py src/resume_agent/api/schemas/match_gap.py src/resume_agent/api/routers/match_gap.py
```

Commit: `feat(api): include suggestion status in match-gap snapshot`

---

## Task 3 — Managed executor lanes in RunManager

**Files:**

- Modify `src/resume_agent/api/runs/manager.py`
- Modify `src/resume_agent/api/app.py`
- Modify `src/resume_agent/config.py`
- Modify `tests/api/test_run_manager.py`
- Modify `tests/api/test_app_health.py` if lifecycle assertions belong there
- Modify `tests/test_config.py`

### Step 1: Add failing concurrency and ownership tests

Test with synchronization events, not sleeps:

1. `suggestion_batch_concurrency` defaults to 3 and rejects 0 and values above
   16.
2. At most N suggestion functions enter concurrently.
3. While the suggestion lane is saturated, a default-lane run completes.
4. `shutdown()` closes every manager-created executor exactly once.
5. An injected executor is used but not shut down by `RunManager`.
6. Existing inline-executor tests remain deterministic.

### Step 2: Implement lanes behind the existing submit interface

- Let `RunManager` accept per-kind worker counts for manager-owned lanes.
- Route `submit(kind, fn)` to the matching lane or the default executor.
- Preserve current run IDs, progress files, cancellation, SSE, and terminal
  states.
- Track ownership per executor and shut down only owned executors.
- In `create_app`, configure the suggestion lane only when the manager owns its
  production executors; keep dependency injection explicit in tests.

Do not add a router semaphore. The concurrency policy belongs in the run module,
where it provides locality and cannot starve unrelated run kinds.

### Step 3: Verify

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py tests/api/test_app_health.py tests/test_config.py -v
.venv/Scripts/ruff.exe check src/resume_agent/api/runs/manager.py src/resume_agent/api/app.py src/resume_agent/config.py
```

Commit: `feat(runs): isolate suggestion work in a managed executor lane`

---

## Task 4 — Shared suggestion submission and multi-target interface

**Files:**

- Create `src/resume_agent/services/suggestion_runs.py`
- Modify `src/resume_agent/api/schemas/suggestions.py`
- Modify `src/resume_agent/api/routers/suggestions.py`
- Modify `tests/test_services_suggestions.py` or create
  `tests/test_services_suggestion_runs.py`
- Modify `tests/api/test_schemas_suggestions.py`
- Modify `tests/api/test_suggestions.py`

### Step 1: Add interface tests

Define request/output types before route code:

- `SuggestionTarget` forbids extra fields and validates kind/key.
- `SuggestionRunsRequest.targets` has length 1–25.
- Accepted and not-found outputs are a discriminated union by `outcome`.
- Generated OpenAPI produces a useful TypeScript union, not `Record<string,
  unknown>`.

Route tests cover:

- dedupe with first-seen order;
- mixed accepted/not-found outcomes;
- one run per accepted target;
- empty/oversized/invalid requests return the existing validation envelope;
- internal generation setup failures are not mislabeled `not_found`;
- the legacy single route and batch route invoke the same submission module;
- each worker opens its own DB session and returns `{kind,key}`.

### Step 2: Implement the deep submission module

Expose a small interface that launches one validated target. Hide context
resolution, worker closure construction, agents, verifier, engine, token, and
worker session inside the module. The batch router performs ordered dedupe and
per-target resolution, then calls that interface.

Keep `POST /api/suggestions/generate` unchanged externally. Add
`POST /api/suggestion-runs`; do not add `/generate-batch`.

### Step 3: Verify

```powershell
.venv/Scripts/python.exe -m pytest tests/test_services_suggestion_runs.py tests/api/test_schemas_suggestions.py tests/api/test_suggestions.py -v
.venv/Scripts/ruff.exe check src/resume_agent/services/suggestion_runs.py src/resume_agent/api/schemas/suggestions.py src/resume_agent/api/routers/suggestions.py
```

Commit: `feat(suggestions): add ordered multi-target run submission`

---

## Task 5 — Regenerate the contract at the backend checkpoint

**Files:**

- Regenerate `contracts/openapi.json`
- Regenerate `contracts/ts/api.ts`
- Modify `web/src/lib/api/schema.ts` only through the existing generation flow

### Steps

1. Run all focused backend tests from Tasks 1–4.
2. Regenerate the client.
3. Run the drift gate and inspect the diff for additive fields, the
   discriminated result union, and the absence of `/suggestions/status` and
   `/suggestions/generate-batch`.

```powershell
bash scripts/gen_ts_client.sh
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v
git diff --check
```

Commit: `chore(contracts): regenerate match-gap and suggestion-run types`

---

## Task 6 — Filter-aware frontend derivation and run-state model

**Files:**

- Modify `web/src/features/match-gap/aggregate.ts`
- Modify `web/src/features/match-gap/aggregate.test.ts`
- Modify `web/src/lib/runs/store.ts`
- Modify `web/src/lib/runs/sse.ts`
- Create `web/src/features/match-gap/suggestion-run-registry.ts`
- Create `web/src/features/match-gap/use-suggestion-runs.ts`
- Create associated tests

### Step 1: Add failing pure derivation tests

Cover:

- edges join nodes by `skillKey`, never display label;
- company/seniority filters recompute skill and theme values;
- gaps-only recomputes score/count/radius inputs from visible skills;
- `filteredJobCount` drives the metric row;
- ready skills float, while stale/queued/researching/failed preserve demand
  order;
- ties use display label then stable key;
- `jobsForSkill` accepts the stable key;
- status lookup is O(1) by `(kind,key)`.

### Step 2: Add failing run-state tests

Cover:

- backend `pending` maps to `queued`;
- progress upserts preserve target metadata;
- each accepted batch result registers its target/run pair;
- `not_found` is retained per target;
- failed/cancelled remains retryable after the global progress bar disappears;
- success invalidates `['match-gap']`, awaits refetch, then clears local state;
- siblings complete/fail independently;
- launch rejection resets the mutation-pending state.

### Step 3: Implement the state model

- Extend the global run status union with `queued` and merge existing run fields
  on upsert.
- Keep target/run/outcome mapping in one feature-local registry; do not overload
  terminal `result` as launch metadata.
- Implement one effective-state function used by list, map, modal, and tray.
- Use TanStack Query invalidation on each successful completion and await the
  active match-gap refetch before clearing transient state.

### Step 4: Verify

```powershell
cd web
npx vitest run src/features/match-gap/aggregate.test.ts src/features/match-gap/suggestion-run-registry.test.ts src/features/match-gap/use-suggestion-runs.test.tsx src/lib/runs
npx tsc --noEmit
```

Commit: `feat(match-gap): derive stable filtered views and per-target run state`

---

## Task 7 — shadcn foundation, workspace shell, and ranked outline

**Files:**

- Add missing `@shadcn` primitives through the CLI
- Modify `web/src/index.css`
- Modify `web/src/features/match-gap/Filters.tsx`
- Rewrite `web/src/features/match-gap/MatchGapContainer.tsx`
- Rewrite `web/src/features/match-gap/RankedList.tsx`
- Delete `WordCloud.tsx`, `WordCloud.test.tsx`, `StatTables.tsx`
- Add/update component tests

### Step 1: Refresh component context before editing

```powershell
cd web
npx shadcn@latest info --json
npx shadcn@latest search '@shadcn' -q 'empty'
npx shadcn@latest search '@shadcn' -q 'field'
npx shadcn@latest docs tabs dialog sheet checkbox collapsible accordion badge skeleton empty alert tooltip field select spinner
npx shadcn@latest add '@shadcn/empty' '@shadcn/alert' '@shadcn/field' '@shadcn/spinner' --dry-run
```

Inspect the dry run. Add only missing primitives, then read every added file.
Do not overwrite installed components. Confirm imports use `@/components/ui`,
Base UI APIs, and Lucide.

### Step 2: Add failing interaction and accessibility tests

Test:

- both tabs, filter persistence, and basket persistence;
- filter-aware metric values;
- accessible loading/error/no-jobs/no-filter-results states;
- theme disclosure and chunked “Show N more” behavior;
- theme and skill selection without nested controls;
- ready-only status sorting and visible status text;
- no company/position tables or word cloud;
- axe has no violations.

### Step 3: Implement the design system foundation

- Add semantic gap/covered/ready variables to `index.css` for light/dark themes.
- Correct `Filters` to Base UI `Select items`, `SelectGroup`, `Field`, and the
  existing Base `ToggleGroup` array value.
- Use controlled `Tabs` in the container.
- Use `Collapsible` or Base `Accordion` for theme rows; custom triggers use
  `render`.
- Compose row layout so Checkbox, disclosure, and detail actions are siblings.
- Show 12 themes and 8 skills per theme, revealing one chunk per action.
- Use `Badge`, `Skeleton`, `Alert`, `Empty`, `Separator`, and existing Button
  variants before custom markup.

### Step 4: Verify

```powershell
cd web
npx vitest run src/features/match-gap/Filters.test.tsx src/features/match-gap/RankedList.test.tsx src/features/match-gap/MatchGapContainer.test.tsx
npx tsc --noEmit
npx eslint src/features/match-gap
```

Commit: `feat(match-gap): build accessible theme-first workspace and outline`

---

## Task 8 — Deterministic accessible constellation

**Files:**

- Modify `web/package.json`, `web/package-lock.json`
- Create `web/src/features/match-gap/skill-map-layout.ts`
- Create `web/src/features/match-gap/skill-map-layout.test.ts`
- Create `web/src/features/match-gap/SkillMap.tsx`
- Create `web/src/features/match-gap/SkillMap.test.tsx`
- Modify `MatchGapContainer.tsx`

### Step 1: Install exact dependencies

```powershell
cd web
npm install d3-force d3-zoom
npm install --save-dev @types/d3-force @types/d3-zoom
```

### Step 2: Test the layout interface before rendering

Tests must prove:

- collapsed graph contains only prefixed theme IDs;
- expanding a theme adds prefixed stable skill IDs and links;
- a third expansion evicts the least-recently expanded theme;
- radius clamps zero, tiny, and extreme scores;
- same stable IDs produce the same coordinates regardless of input order;
- inputs and link endpoints are not mutated;
- all coordinates are finite and within the expected centered extent;
- empty and unthemed inputs are valid.

Implementation requirements:

- clone nodes and links before passing them to d3;
- seed initial positions from a stable string hash;
- set a deterministic `randomSource`;
- call `stop()` and a fixed number of `tick()` iterations;
- keep d3 types private and return immutable render nodes/links.

### Step 3: Test and implement the map UI

Component tests cover:

- theme expand/collapse from pointer, Enter, and Space;
- skill detail opening and independent Checkbox selection;
- zoom in/out/reset and cleanup;
- `ResizeObserver` resize;
- ready ring plus visible ready label;
- legend/instructions/text summary;
- stale clusters and no filtered skills;
- reduced motion and axe.

Render SVG links under absolutely positioned HTML node controls. Do not attach
button roles to SVG circles. Keep at most two expanded themes in the DOM.

### Step 4: Verify

```powershell
cd web
npx vitest run src/features/match-gap/skill-map-layout.test.ts src/features/match-gap/SkillMap.test.tsx
npx tsc --noEmit
```

Commit: `feat(match-gap): add deterministic accessible skill constellation`

---

## Task 9 — Skill modal

**Files:**

- Create `web/src/features/match-gap/SkillModal.tsx`
- Create `web/src/features/match-gap/SkillModal.test.tsx`
- Modify `MatchGapContainer.tsx`
- Delete `SkillDrawer.tsx`, `SkillDrawer.test.tsx`

### Step 1: Add failing tests

Cover:

- controlled open/close and focus return;
- visible `DialogTitle` and `DialogDescription`;
- stable key is passed to `useSuggestion` and generation;
- raw phrasings sort by count then text;
- source mix and filtered demanding roles;
- suggestion/roles tabs;
- loading/error/empty suggestion states;
- responsive single/two-column layout and axe.

### Step 2: Implement

- Reuse the Job modal's information hierarchy only.
- Use semantic tokens, existing radius scale, and subtle/no shadow.
- Compose a full `Dialog`; avoid manual overlay z-index.
- Keep scroll inside the dialog and preserve a usable 320 px layout.
- Reuse `SuggestionPanel` without duplicating its generation behavior.

### Step 3: Verify

```powershell
cd web
npx vitest run src/features/match-gap/SkillModal.test.tsx src/features/match-gap/SuggestionPanel.test.tsx
npx tsc --noEmit
```

Commit: `feat(match-gap): replace skill sheet with evidence dialog`

---

## Task 10 — Responsive selection tray and multi-run wiring

**Files:**

- Create `web/src/features/match-gap/SelectionTray.tsx`
- Create `web/src/features/match-gap/SelectionTray.test.tsx`
- Modify `use-suggestion-runs.ts`
- Modify `MatchGapContainer.tsx`

### Step 1: Add failing tests

Cover:

- desktop sticky aside and mobile titled `Sheet`;
- typed theme and skill targets from map/list;
- clear/remove without corrupting keys containing punctuation or colons;
- `Generate all` sends one ordered target list and disables only during launch;
- accepted, not-found, queued, researching, ready, stale, failed, and cancelled
  labels/icons;
- per-item retry;
- mixed sibling outcomes;
- focus behavior when the mobile sheet opens/closes;
- axe.

### Step 2: Implement

- Keep the desktop tray in grid layout; do not cover workspace content with a
  fixed panel.
- Use `SheetTitle` and `SheetDescription` on mobile.
- Use `Alert` for launch-level failure and per-row text for item failure.
- Use Button variants and icons with `data-icon`; no emoji-only controls.
- Watch each accepted run independently and invalidate `['match-gap']` after
  each success.

### Step 3: Verify

```powershell
cd web
npx vitest run src/features/match-gap/SelectionTray.test.tsx src/features/match-gap/use-suggestion-runs.test.tsx src/features/match-gap/MatchGapContainer.test.tsx
npx tsc --noEmit
```

Commit: `feat(match-gap): add responsive multi-target suggestion tray`

---

## Task 11 — Full verification and documentation consistency

### Backend

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check src tests
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v
```

### Frontend

```powershell
cd web
npm run test:run
npm run lint
npm run build
```

### Responsive browser pass

At 320, 768, 1024, and 1440 px verify:

- map/list/filter/tray state persistence;
- keyboard-only theme, skill, selection, modal, zoom, and retry paths;
- no content hidden behind the tray or dialog;
- dark theme contrast and semantic state colors;
- reduced motion;
- no console errors or accessibility violations.

### Final audits

- Run `git diff --check`.
- Search for deleted imports and deprecated routes:

```powershell
rg -n "WordCloud|StatTables|SkillDrawer|suggestions/status|generate-batch" web src tests contracts docs/superpowers
```

- Confirm any remaining hits are migration notes in these reviewed documents.
- Confirm unrelated pre-existing worktree changes remain untouched.

Commit: `test(match-gap): verify redesigned dashboard end to end`

## Review gates

Do not begin a later phase while its dependency gate is red:

1. Tasks 1–5: backend tests and generated contract green.
2. Task 6: stable key/status derivation green before any component consumes it.
3. Task 7: shell/list accessible before map complexity is introduced.
4. Task 8: pure layout tests green before map rendering.
5. Tasks 9–10: modal/tray integration green.
6. Task 11: full suites, lint, build, drift, responsive, and accessibility green.

## Bugs explicitly removed from the previous plan

- No display label is used as a persistent key.
- No second traversal rebuilds edges after choosing labels.
- No lexicographically reversed tie-break from `max((count, string))`.
- No unfiltered server theme score is shown after client filtering.
- No ambiguous single theme `score` across two weighting modes.
- No global executor resize, unowned executor leak, or shared-worker semaphore.
- No duplicated single/batch suggestion worker closure.
- No unpaginated suggestion-status request or duplicate graph build.
- No use of terminal run `result` as in-flight target metadata.
- No transient failed state disappearing with the global progress bar.
- No colon-splitting target identifiers.
- No status-induced list reshuffle for queued/researching/failed items.
- No mutation-based d3 determinism test or caller-owned d3 input mutation.
- No unlimited expanded map themes.
- No keyboard-inaccessible SVG `role="button"` circles.
- No nested Checkbox inside row button.
- No Radix `asChild` in this Base UI project.
- No missing Dialog/Sheet titles, ungrouped Select items, raw status colors, or
  custom loading/empty primitives.
