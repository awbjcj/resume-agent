# Match / Gap dashboard redesign — design

**Date:** 2026-06-27
**Status:** Reviewed; approved for implementation
**Supersedes interaction:** the current `web/src/features/match-gap/` dashboard
(`MatchGapContainer` + `RankedList` + `WordCloud` + `StatTables` + `SkillDrawer`)
and refines the 2026-06-26 match-gap intelligence and gap-closing advisor
designs.

---

## 1. Outcome

The dashboard becomes a technical skill atlas: a theme-first workspace with an
interactive constellation, a dense ranked outline, a large evidence modal, and
a persistent multi-select suggestion queue.

It must solve seven problems:

1. Plot themes and generalized skills as an interactive node-link map.
2. Replace the narrow skill `Sheet` with a large evidence `Dialog`.
3. Make thousands of skills scannable by grouping and progressively revealing
   the long tail.
4. Remove redundant company/position tables and keep filtering in one place.
5. Show persisted and live suggestion status consistently in every view.
6. Generate advice for generalized skills, not raw JD phrasings.
7. Launch and monitor multiple suggestion runs without exhausting the shared
   run executor.

## 2. Domain model and stable identity

The taxonomy has three tiers:

| Tier | Example | Identity | Role |
| --- | --- | --- | --- |
| Theme | Backend | stable `themeId` | map hub and ranked group |
| Generalized skill | Python | stable canonical `key` | actionable suggestion target |
| Raw phrasing | Python 3.x | exact trimmed string | evidence shown in the modal |

The generalized-skill `key` is the canonical alias survivor from `ClusterMap`.
It is not a display label. `skill` remains the human-readable label for backward
compatibility, chosen from the most frequent raw phrasing. Ties are resolved by
`casefold()` ascending, then the original string ascending. Changing frequency
may change `skill`; it must never change the `key`, selection identity,
suggestion cache identity, graph node identity, or React key.

Suggestions default to `kind="skill"` with the stable generalized-skill key.
`kind="theme"` remains available for deliberate whole-theme learning paths.
Raw phrasings are never suggestion targets.

Legacy persisted suggestion rows may use the old display label as their key.
Reads resolve canonical keys first, then current display labels as a compatibility
fallback. A successful regeneration rewrites the legacy row to the canonical
key. If canonical and legacy rows both exist, the canonical row wins. This is a
one-version migration path, not a second public contract.

## 3. Backend architecture

### 3.1 Deepen the demand-graph module

`tracking.match_gap.build_demand_graph` remains the single module that owns
normalization, aliasing, distinct-job counting, source counting, display-label
selection, edge projection, and theme aggregation. Callers receive a complete
graph; they do not reproduce aggregation rules.

For each generalized skill, accumulate:

- `key: str` — stable canonical identity.
- `skill: str` — display label retained for existing consumers.
- `members: dict[str, int]` — exact trimmed phrasing to distinct-job count.
- `must`, `nice`, `tech: int` — distinct-job count per source.
- `jobCount: int` — distinct demanding jobs across all sources.
- `themeId` and `covered` — existing classification.

For each edge, add `skillKey` while retaining the existing display `skill`.
The implementation accumulates edges by canonical key and projects the final
display label once; it must not perform a second database/job traversal.

For each theme, expose unfiltered baseline aggregates:

- `essentialScore` — sum of `must*3 + nice*2 + tech` over member skills.
- `popularScore` — sum of generalized-skill distinct-job counts.
- `jobCount` — distinct jobs demanding at least one member skill.
- `skillCount` and `gapCount`.

These values describe the unfiltered graph. The dashboard always recomputes
theme metrics from filtered edges when company, seniority, gaps-only, or
weighting changes.

Counting invariants:

- Repeating one exact phrasing in one job counts once in `members`.
- The same canonical skill in two source arrays counts once in each source and
  once in `jobCount`.
- Blank normalized keys are dropped.
- Output order is deterministic and independent of input insertion order.
- Missing or stale clustering assigns skills to the synthetic client group
  `__unthemed__`; no synthetic theme is persisted.

### 3.2 Dashboard snapshot instead of a status-list endpoint

`GET /api/match-gap` remains the dashboard read interface. Extend
`MatchGapOut` additively with `suggestionStatuses` rather than adding a second
unpaginated status-list request.

Each status row is `{kind, key, state, generatedAt}` where `state` is `ready` or
`stale`. The router builds the demand graph once, then a suggestion catalog
module joins persisted `SkillSuggestion` rows to that graph and computes the
current fingerprint. Rows whose targets are no longer in the graph are omitted.

This gives the client one internally consistent snapshot, avoids duplicate graph
construction, and avoids N per-skill reads. Completing a suggestion run
invalidates the existing `match-gap` TanStack Query key.

### 3.3 Suggestion run submission module

Single and batch launch routes must share one implementation. Add a suggestion
run submission module that owns context resolution, worker closure construction,
agent construction, repository verification, worker-session lifetime, and
`RunManager.submit`. Routers only validate requests and serialize outcomes.

Keep the existing `POST /api/suggestions/generate` interface for compatibility;
delegate it to the shared module.

Add `POST /api/suggestion-runs`:

```json
{
  "targets": [
    { "kind": "skill", "key": "python" },
    { "kind": "theme", "key": "backend" }
  ]
}
```

Rules:

- `targets` contains 1–25 items; models forbid extra fields.
- Keys are trimmed, non-empty, and at most 200 characters.
- Exact duplicate `(kind, key)` pairs collapse, preserving first-seen order.
- Every valid target produces one independent suggestion run.
- Unknown targets are per-item outcomes and do not abort valid siblings.
- Response order matches the deduplicated request order.

The `202` response is a discriminated list:

```json
{
  "results": [
    { "outcome": "accepted", "kind": "skill", "key": "python", "runId": "..." },
    { "outcome": "not_found", "kind": "theme", "key": "missing" }
  ]
}
```

All validation errors use the existing structured API error interface. Internal
exceptions never leak through per-item `not_found` handling.

### 3.4 Per-kind run executor lanes

Do not resize the shared executor and do not wait on a semaphore inside a shared
worker. Both approaches let a large suggestion batch starve unrelated runs.

Deepen `RunManager` with managed per-kind executor lanes. The constructor accepts
`kind_workers={"suggestion": Settings.suggestion_batch_concurrency}`; `submit`
selects the suggestion lane by run kind and otherwise uses the existing default
executor. `RunManager` owns and shuts down every executor it creates. Injected
executors remain caller-owned.

`suggestion_batch_concurrency` defaults to 3 and validates `1 <= value <= 16`.
Direct single-suggestion launches use the same lane, so the cap is global across
single and batch launches. Tests must prove both the cap and that a saturated
suggestion lane does not block a non-suggestion run.

## 4. Frontend information architecture

### 4.1 Visual direction

Use a restrained technical-atlas aesthetic that fits the existing neutral/teal
application: crisp borders, compact editorial typography, a subtle plotted
background in the map, and one semantic amber/gold token for generated advice.
Avoid gradients, oversized cards, heavy shadows, and decorative rounding.

All state colors are semantic CSS variables in `web/src/index.css`; light and
dark values are defined together. Color is never the only signal: every state
also has text and an icon. Existing Geist typography and the project spacing
scale remain authoritative.

### 4.2 Workspace shell

`MatchGapContainer` owns filters, active tab, open skill, and the typed selection
basket. Layout:

1. `PageHeader`.
2. Sticky filter bar.
3. Filter-aware metrics: matching jobs, visible generalized skills, open gaps.
4. `Tabs`: `Map` and `Ranked list`.
5. Selection tray as a desktop sticky rail or mobile `Sheet`.

Filters persist across tab changes. Selection identity is `(kind, stable key)`,
stored as typed targets rather than colon-delimited strings. Removing
`WordCloud` and `StatTables` does not remove their filter coverage.

The existing Base UI shadcn project is authoritative. New implementation uses:

- `TabsList` containing all `TabsTrigger` elements.
- `Collapsible`/`Accordion` for theme disclosure.
- `Checkbox` as a sibling of row actions, never nested inside a button.
- `Badge` for status, `Skeleton` for loading, `Alert` for failures, and `Empty`
  for empty states.
- `Dialog` with a visible `DialogTitle` and `DialogDescription`.
- Base UI `render`, not Radix `asChild`, for custom triggers.
- Lucide icons with `data-icon` in buttons and no manual icon sizing there.

The plan includes adding missing `@shadcn` primitives and correcting the current
filter controls to use Base UI `Select items`, `SelectGroup`, and `Field`.

### 4.3 Ranked outline

Theme rows are ranked by the currently selected weighting and filtered edges.
Each row shows label, score, visible skill count, gap count, a demand bar, a
selection checkbox, and a disclosure control. Expanding shows generalized-skill
rows with label, job frequency, coverage, suggestion status, selection checkbox,
and an explicit detail action.

Only `ready` suggestions float above normal demand order. `researching`,
`queued`, `failed`, and `stale` remain in demand order so transient state does
not reshuffle the list. Ties use label then stable key.

Initially show 12 themes and 8 skills per expanded theme. “Show N more” reveals
the next chunk; it never mounts the full long tail at once. Counts always report
the complete filtered totals.

### 4.4 Constellation map

The map renders theme hubs initially and allows at most two expanded themes.
Expanding a third collapses the least recently expanded theme. Skill leaves link
only to their theme hub.

`d3-force` computes positions synchronously from cloned nodes and links. The
layout seeds positions from stable IDs, sets a deterministic random source,
stops the simulation, ticks a fixed count, and never mutates caller-owned input.
`ResizeObserver` supplies the plot dimensions. `d3-zoom` controls a shared
transform and is cleaned up on unmount.

React renders SVG links and an HTML node layer. Real `<button>` and `Checkbox`
controls provide keyboard, focus, and screen-reader behavior; no SVG circle is
given a fake button role. The map includes zoom in/out/reset controls, a legend,
concise usage instructions, and a synchronized textual summary.

Encoding:

- Radius = clamped square root of current filtered score.
- Theme hub = primary semantic token.
- Gap = semantic gap token; covered = muted token.
- Ready suggestion = semantic ready ring plus `Ready` label/tooltip.
- Focus and selection have distinct non-color treatments.

With no themes, visible skills appear under one `Unthemed` hub. With no visible
skills after filtering, use `Empty` and keep filter-reset and cluster-refresh
actions available.

### 4.5 Skill detail modal

`SkillModal` uses the Job modal's information hierarchy, not its bespoke shadow
or rounded styling. It is a controlled `Dialog` with a large desktop layout and
a single-column mobile layout.

- Masthead: display label, theme, coverage, persisted/live status, demand count.
- Evidence rail: raw phrasings sorted by count, source mix, demanding roles.
- Main tabs: `Suggestion` and `Roles`.
- `SuggestionPanel` remains the content module and targets the stable key.

Focus returns to the invoking control on close. Long content scrolls inside the
dialog; the page behind it does not.

### 4.6 Selection tray and effective status

The basket supports skill and theme targets from either view. Desktop uses a
sticky `<aside>` that participates in layout; mobile uses a titled `Sheet`.
Each item shows label, status text/icon, remove, and retry where applicable.

Persisted `ready`/`stale` state comes from the match-gap snapshot. A feature-local
run registry maps each launched run ID to its target and retains the latest
failed/cancelled outcome until retry or dismissal. Effective precedence is:

1. queued or running local run;
2. retained failed/cancelled outcome;
3. persisted ready or stale status;
4. none.

On success, keep the item in `researching` until invalidating and refetching the
match-gap query completes, then clear the local run state. This prevents a flash
from `researching` back to `none`. The global SSE store maps backend `pending`
to `queued` and preserves feature metadata when progress records merge.

“Generate all” is disabled while the launch request is pending, reports
per-target `not_found` outcomes, and watches every accepted run independently.
One failed run never blocks sibling completion or retry.

## 5. Accessibility, responsiveness, and performance

- WCAG 2.1 AA contrast; status is never color-only.
- Logical headings with one page `h1`.
- Full keyboard path through tabs, theme disclosure, map nodes, checkboxes,
  dialog, tray, zoom controls, and retries.
- Reduced-motion mode removes animated transitions.
- Tested widths: 320, 768, 1024, and 1440 px.
- Loading, request error, no jobs, no filter matches, stale clustering, partial
  batch failure, and total batch failure all have explicit states.
- Only two themes' skill nodes exist in the map at once; ranked long tails are
  chunked; status lookup is O(1) by stable target key.

## 6. Out of scope

- Changing the legacy `match_gap()` CLI report.
- Co-occurrence edges between skills.
- Suggestions for raw phrasings.
- Replacing the clustering algorithm or refresh run.
- Persisting background run state across browser reloads.

## 7. Acceptance criteria

- Display-label changes do not orphan selections or persisted suggestions.
- Exact raw-phrasing and source counts obey distinct-job semantics.
- Filtered theme scores, counts, map radii, and metrics agree.
- One match-gap request supplies graph data and persisted suggestion statuses.
- Batch results are ordered, typed, bounded, and partial-success safe.
- Suggestion concurrency cannot starve unrelated run kinds.
- Map and list expose the same targets and effective statuses.
- Every interactive control is keyboard accessible and axe-clean.
- Backend tests, frontend tests, TypeScript, lint, OpenAPI drift, and production
  build pass.
