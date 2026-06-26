# Match/Gap → Skill-Demand Intelligence Dashboard (Spec A)

**Date:** 2026-06-26
**Status:** Approved (design)
**Scope note:** This is **Spec A** of a two-spec split. Spec B — the LLM
web-search "how to close this gap" advisor (GitHub repos / learning resources,
DeepSeek-vs-Gemini/OpenAI web-search capability check) — is deliberately deferred
to its own spec. The `{skill, jobs, theme}` shapes this spec produces are Spec B's
input.

---

## 1. Problem & reframe

Today the Match/Gap feature shows a flat, read-only table of **only the skills the
profile lacks**, demanded by target jobs (`shortlisted`→`rendered`, non-archived),
drawn from `must_have_skills` alone. The backend already computes a `per_job`
reverse index but never exposes it, and the LLM synonym canonicalizer that exists
(`tracking/canonicalize.py`) is **not wired into the match-gap path** — the router
calls `match_gap(session, facts)` with no canonicalizer, so counts double-count
synonyms (k8s vs kubernetes).

The redesign reframes the page from a **gap table** into a **skill-demand
intelligence dashboard**: aggregate *every* skill demanded across target jobs, carry
each skill's coverage as a flag (covered vs gap), let the user slice the data by
company and by position/seniority, see weighted popularity as a word cloud + ranked
list, drill from any skill/theme to the exact jobs that demand it, and dedup +
thematically cluster skills with LLM calls done off the read path.

### Decisions locked during brainstorming

| # | Decision |
|---|----------|
| 1 | **Split** the work: Spec A (this) = analytics redesign; Spec B = web-search advisor. |
| 2 | **Core frame:** skill-demand intelligence; gap is a per-skill flag, not the whole dataset. |
| 3 | **Skill source:** all three lists, **weighted** — `must_have`=3, `nice_to_have`=2, `tech_stack`=1 (tunable constants). "Essential" = high must-have weight; "popular" = many jobs. |
| 4 | **Dedup placement:** a **background refresh Run** persists clusters; the dashboard GET reads them. No LLM in the read path. |
| 5 | **Cluster meaning:** **both** layers — (1) synonym dedup for correct counts, (2) thematic grouping for the cloud and future skill-set suggestions. |
| 6 | **Interactions (all four):** click skill/theme → jobs drawer; filter by company; filter by position/seniority; toggle gaps-only vs all-demand + weighting (Essential ↔ Popular). |
| 7 | **Compute locus:** one rich GET returns the demand graph; **all filtering/aggregation is client-side**. |
| 8 | **Layout:** split — word cloud + ranked list side-by-side, stat breakdowns below, drill-down drawer on the right. |

---

## 2. Backend

### 2.1 The demand graph (rich GET projection)

`GET /api/match-gap` returns the demand graph once; the client derives every view
from it.

```
MatchGapOut {
  targetTotal: int
  clustersStale: bool                    # jobs reference skills not yet in the persisted cluster map
  jobs:   [JobLite { id, company, title, seniority }]      # drill-down labels + filter facets
  skills: [SkillNode { skill, themeId|null, covered: bool }]  # deduped skill universe + coverage
  edges:  [DemandEdge { jobId, skill, source: "must"|"nice"|"tech" }]
  themes: [Theme { id, label }]
}
```

- `skill` on both `skills[]` and `edges[]` is the **canonical** display string (post-dedup).
- `covered` is computed **deterministically** in the projection: `profile_skill_tokens(facts)`
  (existing) tested against the canonical skill. **No LLM in the read path.**
- `edges[]` carries `source` so the client can recompute weighted demand under any
  filter (e.g. filter to one company → re-sum that subset).
- Skills present on jobs but absent from the persisted cluster map pass through as
  identity-canonical with `themeId = null`, and set `clustersStale = true`.

**Why ship edges, not pre-aggregated rows:** filtering by company/seniority must
re-weight from the surviving job subset. Shipping the `{jobId, skill, source}`
edge list (bounded: target jobs × ~10–20 skills ≈ low thousands of rows) lets the
browser recompute weighted demand, job counts, and by-company / by-position
rollups with zero round-trips. Payload stays in the KB–low-MB range.

`per_job` (today's unused field) is subsumed by `edges[]`.

### 2.2 Aggregation source

`match_gap` (in `tracking/match_gap.py`) changes from "must-have only, gaps only"
to "all three lists, all skills":

- Read `must_have_skills`, `nice_to_have_skills`, `tech_stack` from each target
  job's `criteria_json` (helper analogous to today's `_must_have_skills`, one per
  source, each tagged with its `source`).
- Build `edges` (one per job×skill×source), `skills` (deduped union with coverage +
  theme), `jobs` (id/company/title/seniority), `themes`.
- Weight constants `WEIGHT = {"must": 3, "nice": 2, "tech": 1}` live as a module
  constant (tunable). The **backend does not pre-multiply** — it emits raw edges and
  lets the client apply weights, so the Essential↔Popular toggle is a pure client
  re-sum.

### 2.3 Cluster map persistence (extend the taxonomy seam)

`taxonomy/skills.py` already persists a flat `token→canonical` alias map via
`refresh_aliases` / `merge_aliases` (monotonic, existing choices win for stability).
Extend this into a **cluster map** with three parts, persisted as JSON under
`data/profile/` (alongside facts) or `data/taxonomy/`:

```
cluster_map.json {
  aliases:    { token: canonical }          # synonym dedup (today's map)
  themeOf:    { canonical: themeId }         # thematic assignment
  themeLabel: { themeId: label }             # display label per theme
}
```

Merges stay **monotonic** (existing canonical/theme choices win) so the dashboard is
stable across refreshes. Loading is identity-on-missing (no file → empty maps →
everything passes through, `clustersStale = true`).

### 2.4 Refresh Run (LLM dedup + theming, off the read path)

`POST /api/match-gap/refresh-clusters` → `202` + run record, watchable at
`GET /api/runs/{id}/events` (SSE) — the established Run+SSE pattern. The worker:

1. Opens its **own DB session** bound to the app engine (never the request session).
2. Collects the skill-token universe across current target jobs.
3. **Pass 1 — dedup:** the existing `build_skill_canonicalizer` (cheap tier).
   Strengthen its prompt for recall on common stacks; output → `aliases`.
4. **Pass 2 — theming:** a **new** agent (`build_skill_themer` or similar, cheap
   tier, structured output `{ themes: [{ label, skills: [...] }] }`) assigns each
   canonical skill to a theme; output → `themeOf` + `themeLabel`.
5. Persists via a monotonic merge into `cluster_map.json`.

Both passes run under the existing concurrency seam (`gather_isolated` + shared
`asyncio.Semaphore`, acquired only inside `llm_runner.acall`). Uses agno's
per-agent retry config (`retry_kwargs()`). A failed pass leaves the prior map intact.

**Trigger:** manual button in the UI (decided over auto-after-pull). `clustersStale`
drives its prominence.

### 2.5 Schemas & contract

- New/changed Pydantic `CamelModel` schemas in `api/schemas/match_gap.py`:
  `MatchGapOut`, `JobLite`, `SkillNode`, `DemandEdge`, `Theme`. camelCase wire
  format via `to_camel`, projected from the report DTO with `model_validate`.
- Run response reuses the existing run record schema.
- Regenerate `contracts/openapi.json` + `contracts/ts/api.ts` via
  `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the drift
  gate.

---

## 3. Frontend

All under `web/src/features/match-gap/`.

### 3.1 Pure aggregation module — `aggregate.ts`

A React-free, unit-tested function: `(payload: MatchGapOut, filters: Filters) →
DerivedView`. Owns **all** logic:

- Apply filters (company set, seniority set, gaps-only) to `edges` by `jobId`.
- Apply weighting mode (Essential = source weights 3/2/1; Popular = distinct-job
  count) to produce each skill's score.
- Produce: `cloudItems` (skill, score, covered, themeId), `rankedRows` (sorted,
  with exact counts + per-source breakdown), `themeGroups`, `byCompany` table,
  `byPosition` table, and a `jobsForSkill(skill)` reverse lookup.

`DerivedView` is the single contract every component renders from.

### 3.2 Components

- **`Filters`** — shadcn `select` (company), `select` (seniority), `switch`
  (gaps-only), `toggle-group` (Essential ↔ Popular). State in a small `zustand`
  store (or URL params for shareable views).
- **`WordCloud`** — **CSS/flex weighted tag cloud.** Font-size bucketed by score,
  color = gap (accent) vs covered (muted), deterministic order (score desc). Each
  word is a real `<button>` (a11y + click → drawer). Chosen over `@visx/wordcloud` /
  d3-cloud: no new dependency, deterministic (snapshot-testable), accessible,
  themeable with existing tokens. d3-cloud's random spiral packing fights snapshot
  tests and a11y. (Recorded as the single point to revisit if true packing is
  later wanted.)
- **`RankedList`** — bars + exact counts beside the cloud; same click target as the
  cloud. May use existing `recharts`/`chart.tsx` or plain CSS bars.
- **`SkillDrawer`** (shadcn `sheet`) — clicking a skill or theme opens a panel
  listing the exact positions + companies demanding it (reverse index made
  interactive), with the per-source breakdown. This panel is also Spec B's mount
  point for the future advisor.
- **`StatTables`** — by-company and by-position rollups below the cloud/list
  (collapsible `select`/`accordion`).
- **`RefreshClustersButton`** — POSTs `/api/match-gap/refresh-clusters`, watches SSE
  via existing run hooks; prominent when `clustersStale`.

### 3.3 Data hook

`use-match-gap.ts` keeps its `useQuery` shape, now typed to the richer
`MatchGapOut`. A second hook wraps the refresh-run POST + SSE using existing run
infrastructure.

---

## 4. Testing

**Backend (offline — faked LLM, faked network):**
- `match_gap` projection: edges/skills/themes shape, coverage flag, weighting
  inputs, `clustersStale` when skills are unmapped.
- Refresh-Run worker with **faked** canonicalizer + theme agent; persistence merge
  is monotonic; failed pass leaves prior map intact.
- OpenAPI contract drift gate regenerated and green.

**Frontend (vitest + MSW):**
- `aggregate.ts` unit tests: weighting modes, company/seniority filtering,
  gaps-only, by-company/by-position rollups, reverse lookup.
- Component tests: filter wiring re-derives the view; clicking a word opens the
  drawer with the right jobs; `clustersStale` surfaces the refresh button.

---

## 5. Out of scope (→ Spec B)

- Web-search "how to close this gap" suggestions (GitHub repos / courses).
- DeepSeek-vs-Gemini/OpenAI web-search capability check and provider plumbing
  (`llm_runner.py` has no tool/web-search seam today; Spec B adds it).
- Per-skill-set suggestion generation. The `{skill, jobs, theme}` shapes from this
  spec are Spec B's input; the `SkillDrawer` is its mount point.

---

## 6. Files touched (anticipated)

| Path | Change |
|------|--------|
| `src/resume_agent/tracking/match_gap.py` | Reframe to demand-graph report (all 3 sources, edges, coverage, themes). |
| `src/resume_agent/tracking/canonicalize.py` | Strengthen dedup prompt; add theming agent (`build_skill_themer`). |
| `src/resume_agent/taxonomy/skills.py` | Extend alias map → cluster map (aliases + themeOf + themeLabel), monotonic merge. |
| `src/resume_agent/api/schemas/match_gap.py` | New camelCase schemas (JobLite/SkillNode/DemandEdge/Theme/MatchGapOut). |
| `src/resume_agent/api/routers/match_gap.py` | Rich projection GET; new `POST /refresh-clusters` Run endpoint. |
| `src/resume_agent/api/runs/manager.py` (wiring) | Register the refresh-clusters worker. |
| `contracts/openapi.json`, `contracts/ts/api.ts` | Regenerated. |
| `web/src/features/match-gap/aggregate.ts` | New pure aggregation module. |
| `web/src/features/match-gap/*.tsx` | Filters, WordCloud, RankedList, SkillDrawer, StatTables, RefreshClustersButton; rewrite container. |
| `web/src/features/match-gap/use-match-gap.ts` | Richer type + refresh-run hook. |
| Tests (backend + frontend) | As in §4. |
