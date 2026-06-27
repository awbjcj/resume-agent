# Match / Gap dashboard redesign — design

**Date:** 2026-06-27
**Status:** Approved for planning
**Supersedes interaction:** the current `web/src/features/match-gap/` dashboard
(`MatchGapContainer` + `RankedList` + `WordCloud` + `StatTables` + `SkillDrawer`)
and extends the `match-gap-skill-intelligence` / `gap-closing-advisor` specs
(2026-06-26) that shipped it.

---

## 1. Problem

The shipped Match/Gap dashboard surfaces a weighted skill-demand view but has
seven concrete gaps the user identified:

1. The clustered/themed skills are never *plotted* — themes are a flat list. The
   user wants an interactive node-link graph: cluster nodes connected to member
   skills, all interactive.
2. The skill detail lives in a cramped right-side `Sheet` (`sm:max-w-xl`); it
   needs a large modal like the Job detail to hold real content.
3. The ranked-demand list renders **every** skill flat — unusable at thousands.
   It should be cluster-first and dense, with the long tail compacted.
4. The "By company" / "By position" `StatTables` are redundant with filters and
   should be removed; clusters should be prioritized over detailed skills
   everywhere.
5. There is no status tracking of which skills already have generated
   suggestions; those should be surfaced and prioritized in layout.
6. Suggestions should target *generalized* skills (Python ≠ Java) without being
   too detailed (`English fluency` = `English`).
7. The user must be able to multi-select skills and generate suggestions for all
   of them asynchronously.

## 2. Taxonomy — the spine

Three tiers, all already latent in `data/profile/cluster_map.json`
(`ClusterMap`):

| Tier | Example | Source | Role |
| --- | --- | --- | --- |
| **Theme** | "Backend" | `theme_of` / `theme_label` | Graph **hub**, collapsed ranked-list row, grouping unit |
| **Generalized skill** | "Python" | `aliases` survivor (synonym-merged) | **Actionable unit** — graph leaf, expandable list detail, primary suggestion target. `Python ≠ Java`; `English fluency`/`fluent English` → one |
| **Raw phrasing** | `python3`, `Python (3.x)` | raw JD string normalized into a generalized skill | Member detail + its own frequency; **modal only** |

Suggestions fire at the **generalized-skill** tier by default; the existing
`kind=theme` path is **kept** for deliberate whole-theme learning-path requests
(§6), never the default.

## 3. Backend & contract changes

All changes are **additive** to the demand graph. The legacy `match_gap()`
report and the `resume-agent` CLI path are untouched (fact-lock and
source-priority invariants are unaffected — this is read-only analytics over
`criteria_json`).

### 3.1 Retain members + frequencies (`tracking/match_gap.py`)

`build_demand_graph` currently keeps only the **first** raw phrasing per
canonical (`display_for.setdefault(...)`) and emits one edge per canonical,
discarding the per-phrasing detail point 3 needs. Change `SkillNode` to
accumulate:

- `members: dict[str, int]` — raw phrasing → job-frequency (distinct jobs that
  used that exact phrasing).
- `must` / `nice` / `tech: int` — per-source distinct-job counts (the "source
  mix").
- `job_count: int` — distinct demanding jobs (already derivable; make explicit).

Add a `ThemeNode` aggregate: `skill_count`, `gap_count`, `score` (weighted
demand summed over member generalized skills), so the ranked theme rows and hub
sizes do not require the client to re-aggregate from edges. The client *may*
still re-aggregate under filters (company/seniority), so the server values are
the **unfiltered** baseline; filtered recomputation stays client-side in
`aggregate.ts` (which already does this).

`display` for a generalized skill = the highest-frequency member phrasing
(deterministic tiebreak by string), not merely the first seen.

### 3.2 Contract (`api/schemas/match_gap.py`)

Extend `SkillNodeOut` with `members: dict[str,int]`, `must`, `nice`, `tech`,
`jobCount`; extend `ThemeOut` with `score`, `skillCount`, `gapCount`. Regenerate
`contracts/openapi.json` + `contracts/ts/api.ts` via `bash scripts/gen_ts_client.sh`;
the drift gate (`tests/api/test_openapi_contract.py`) must pass.

### 3.3 Suggestion-status endpoint (point 5)

New `GET /api/suggestions/status` → `[{kind, key, state: "ready"|"stale", generatedAt}]`
for every persisted `SkillSuggestion`, with `stale` computed against the current
fingerprint (reuse `suggestion_fingerprint` + the current demand graph + profile
facts, exactly as `get_suggestion` does for one row). This lets the dashboard
badge and sort **without** issuing N per-skill requests. Live `researching` /
`queued` / `failed` states are **not** persisted — they come from the client run
store (§4.3).

### 3.4 Batch generation endpoint (point 7)

New `POST /api/suggestions/generate-batch` accepting
`{ items: [{kind, key}, …] }` (deduped, bounded length). It resolves each
context (404 on any unknown target is reported per-item, not fatal) and spawns
**one independent run per item** via `RunManager.submit("suggestion", work)` —
reusing the existing `generate_suggestion` worker verbatim — bounded by a new
`Settings.suggestion_batch_concurrency` (validated `>= 1`, default e.g. 3). The
endpoint returns `{ runs: [{kind, key, runId}, …] }`. Per-skill status, retry,
and SSE all fall out of the existing run machinery; no new progress plumbing.

Concurrency bound: the batch must not launch an unbounded number of blocking
threadpool workers. Implementation options for the planner: a bounded worker
pool / semaphore inside the batch submission, or a small queue the `RunManager`
drains at the configured width. The existing per-call LLM `Settings.llm_concurrency`
semaphore (inside `llm_runner.acall`) still applies underneath; the suggestion
agents are synchronous (`search_agent.run`), so the **run-level** cap is what
bounds true parallelism here.

## 4. Frontend

Replaces `MatchGapContainer`. New structure under `web/src/features/match-gap/`.

### 4.1 Tabbed workspace shell (layout C)

`MatchGapContainer` becomes: `PageHeader` → sticky **filter bar** (existing
`Filters`: company · seniority · gaps-only · weighting · `RefreshClustersButton`)
→ `Tabs` with `Map` | `Ranked list`. Filters **and** the selection basket live
in container state so both persist across tab switches. `MetricRow` (target
jobs / distinct skills / open gaps) stays above the tabs.

**Removed:** `WordCloud.tsx`, `StatTables.tsx` (point 4 — by-company/by-position
are covered by the company/seniority filters). Their tests are removed with them.

### 4.2 Ranked list — theme rows → skills (points 3, 4, 5)

`RankedList` is rewritten to render **theme rows** ranked by aggregate weighted
demand: each row shows a demand bar, skill count, and gap count, and is
collapsible. Expanding a theme reveals its generalized skills (frequency,
covered/gap, **status badge**). Ordering rules:

- Themes sorted by `score` desc (respecting the `essential`/`popular` weighting
  toggle, computed client-side as today).
- Within an expanded theme, generalized skills sort by `score` desc, but
  **ready-suggestion skills float to the top of their group** (status as
  tiebreaker over demand — point 5, "badge in place + sort within group").
- Long tail compacted: themes past a threshold collapse under "Show N more
  themes"; within a theme, skills past a threshold fold under "Show N more".
- Each skill row carries a **select checkbox** feeding the basket (§4.4) and a
  click target opening the modal (§4.5).

### 4.3 Map — collapsed constellation via d3-force (point 1)

New `SkillMap.tsx`. A `d3-force` simulation renders **theme hubs** by default
(node radius ∝ `sqrt(score)`); `d3-zoom` provides pan/zoom. Clicking a hub
**injects** that theme's generalized-skill nodes + hub→skill links into the
simulation (and re-heats it); clicking empty space or the hub again removes
them — so only 1–2 themes are ever exploded (the "collapsed constellation").
Node encoding (shared with the list/modal):

- **size** = weighted demand,
- **color** = gap (warning) vs covered (muted),
- **gold ring** = a suggestion is `ready` (from §3.3 + run store),
- click a skill node → modal; tick-select → basket.

Rendering: React owns the SVG (`<g>` per node/link); `d3-force` owns positions
via a simulation held in a ref, updated on `tick`. **Testing:** the offline
suite ticks the simulation deterministically (`simulation.stop()` then a fixed
number of `simulation.tick()` calls, seeded initial positions) and asserts on
the resulting React-rendered nodes/edges — no animation, no timers. New deps:
`d3-force`, `d3-zoom`, `@types/d3-force`, `@types/d3-zoom`.

Degenerate case: when `clustersStale` or no themes exist, all skills fall under a
single "Unthemed" hub and the existing `RefreshClustersButton` nudge invites a
cluster refresh (the background Run already exists). The Map must render
something coherent in this state, not crash.

### 4.4 Selection tray (point 7, mockup B)

`SelectionTray.tsx` — a right-side panel that opens when ≥1 skill/theme is
ticked (in the list *or* the Map). It holds the basket, shows **per-item live
status** (○ none · ⏱ queued · ◐ researching · ★ ready · ⚠ failed ↻) by joining
the status endpoint (§3.3) with the client run store, and exposes one
"⚡ Generate all" that calls the batch endpoint (§3.4) and then watches the
returned runs. Per-item retry re-submits just that item. Basket state lives in
container state (persists across tabs).

### 4.5 Skill detail modal (point 2, mockup A — job-modal idiom)

`SkillModal.tsx` built on `Dialog` (mirrors `JobModal`: `max-w-6xl`, masthead +
two-pane). Masthead: skill name + theme pill + gap/covered pill + suggestion
status pill + demand/role counts. Left **evidence rail**: member phrasings +
frequencies, source mix (must/nice/tech), demanding roles. Right **tabbed main**:
`Suggestion` (the existing `SuggestionPanel` content — bridge/repos/resources/
project/citations, generate/regenerate) · `Roles` (the demanding-jobs list).
`SkillDrawer.tsx` (the `Sheet`) is **replaced** by this modal; `SuggestionPanel`
is reused inside it.

### 4.6 Status model (point 5, client)

A `useSuggestionStatus()` query wraps §3.3. Effective per-key state =
`failed`/`researching`/`queued` from the run store if a run is in flight, else
`ready`/`stale` from the status endpoint, else `none`. This single derivation
feeds the Map ring, the list badge/sort, and the tray.

## 5. Phased implementation plan (one spec)

1. **Backend & contract.** Demand-graph members/frequencies + theme aggregates;
   schema extensions + `gen_ts_client.sh` regen + drift gate; `GET /suggestions/status`;
   `POST /suggestions/generate-batch` + `suggestion_batch_concurrency`. Unit
   tests against fixtures (offline).
2. **Frontend shell + ranked list.** Tabbed workspace; theme-row ranked list with
   expand/compaction; status badges + within-group sort; delete `WordCloud` /
   `StatTables`. Wire `useSuggestionStatus`.
3. **Constellation Map.** `SkillMap` with `d3-force`/`d3-zoom`; collapse/expand;
   shared encoding; degenerate `clustersStale` handling; deterministic-tick tests.
4. **Modal + selection tray + batch.** `SkillModal` (replace `SkillDrawer`);
   `SelectionTray`; batch wiring + per-item status/retry.

Each phase ends green (`pytest` for backend, the web test runner for frontend)
and independently reviewable.

## 6. Out of scope

- The `match_gap()` legacy report and CLI (untouched).
- Co-occurrence edges between skills (considered, rejected for v1 in favor of
  theme-hub hierarchy).
- Per-raw-phrasing suggestions ("too detailed" — point 6).
- Changing the clustering/refresh Run itself (only consumed, not modified) beyond
  what the new theme aggregates require.

## 7. Risks & notes

- **Empty/stale clusters** make the Map and theme rows degenerate to "Unthemed";
  handled via §4.3 + the refresh nudge, but the first-run experience depends on a
  cluster refresh having been run.
- **Batch fan-out** must respect `suggestion_batch_concurrency`; a large basket
  must not exhaust the run threadpool. Verified by a test asserting in-flight
  runs never exceed the cap.
- **d3-force is the only new runtime dependency**; its non-determinism is
  contained by ticking synchronously in tests.
- **Contract drift** is the usual gate — every schema change regenerates the TS
  client and must pass `test_openapi_contract.py`.
