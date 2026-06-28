# Durable run tracking + incremental skill classification — Design

**Date:** 2026-06-28
**Branch:** feat/match-gap-dashboard-redesign
**Status:** Approved design (pending spec review)

## Problem

Three coupled complaints:

1. **Progress vanishes on refresh.** A long run's progress bar disappears when the
   page reloads, so the user can no longer track in-flight work.
2. **Coarse progress.** Skill-cluster refresh shows two opaque, multi-minute steps
   (canonicalize, theme) with long stalls — no real-time sense of progress.
3. **Slow classification.** Skill canonicalize/theme each issue one LLM call over
   the *entire* token set, every refresh, with no concurrency and no reuse.

## Root causes (confirmed in code)

- Run state lives only in the frontend Zustand store (`web/src/lib/runs/store.ts`),
  and the SSE subscription (`watchRun`) is created **only at launch time** inside
  `useLaunchRun`. On reload the store is empty and nothing re-subscribes. The
  backend **does** persist each run as a JSON file under `data/runs/` and the
  worker keeps running — but there is **no `GET /api/runs` list endpoint** (only
  `GET /api/runs/{id}`, `/cancel`, `/events`). The data survives; the UI discards it.
- `refresh_clusters` (`src/resume_agent/services/match_gap.py`) reports only
  `begin(2)` → step 1 (canonicalize) → step 2 (theme): two opaque LLM calls.
- `build_skill_canonicalizer` / `build_skill_themer`
  (`src/resume_agent/tracking/canonicalize.py`) each do **one** synchronous LLM
  call over the whole token set; nothing is reused between refreshes.

**Key coupling:** you cannot subdivide a single opaque LLM call's progress.
Finer progress for clustering *requires* breaking the monolithic call into pieces —
which is the same work as batching it for speed. One design serves problems 2 and 3.

## Decisions (settled during design)

| # | Decision | Choice |
| - | -------- | ------ |
| 1 | Status surface | **Rehydrate the existing top bar** — no new dashboard page |
| 2 | Rehydrate scope | **Active only** (non-terminal runs); finished-while-away runs are not shown |
| 3 | Classification strategy | **Incremental + concurrent delta** with a global reconcile pass |
| 4 | Granularity scope | **Only skill clustering**; pull/tailor/discover already report per-job |
| 5 | Refresh-button semantics | **Incremental delta + prune** stale entries; no separate full-rebuild button (YAGNI) |
| 6 | Batch-failure handling | **Tolerate** — skip & retry the failed batch's tokens next run; run still completes |
| 7 | Existing-canonical context | **Pass all existing canonicals** in v1; relevance-capping is a future refinement |

## Existing infrastructure reused (no new substrate)

- Async LLM seam: `acall`, `Runner.arun` (`src/resume_agent/llm_runner.py`),
  `gather_isolated` (`src/resume_agent/concurrency.py`), and
  `asyncio.Semaphore(get_settings().llm_concurrency)` — already used by
  `tailor/service.py` and `discovery/pipeline.py`. Each phase keeps a sync public
  signature and runs `asyncio.run(...)` internally.
- `merge_cluster_map` (`src/resume_agent/taxonomy/clusters.py`) already adds
  entries **without redirecting existing terminal canonical tokens** — the exact
  property incremental classification needs.
- The refresh-clusters router (`api/routers/match_gap.py`) already constructs the
  canonicalizer/themer and passes the run's `ProgressReporter`.
- `RunManager.sweep` already demonstrates the `RUNS_ROOT/*.json` directory scan.

---

## Workstream 1 — Run status survives refresh

### Backend

- **`RunManager.list_active()`** — scan `RUNS_ROOT/*.json`, parse via the tolerant
  `read_progress`, return records whose `state` is non-terminal
  (`pending` / `running` / `cancelling`), sorted by `started_at`. Unreadable files
  are skipped.
- **`GET /api/runs`** → `list[RunOut]` (active only), guarded like the other run
  routes. Reuses the existing `RunOut` schema. Regenerate `contracts/openapi.json`
  + `contracts/ts/api.ts` (`bash scripts/gen_ts_client.sh`); the
  `tests/api/test_openapi_contract.py` drift gate enforces this.

### Frontend

- On mount in `web/src/app/AppLayout.tsx`, fetch `GET /api/runs`; for each active
  run, `useRunStore.upsert(...)` and `watchRun(runId, kind)` to re-attach SSE
  (`kind` comes from the record; `watchRun` requires it).
- Track subscribed `runId`s in a ref/`Set` so an in-session launch that later
  remounts is not double-subscribed.
- `RunPanel` is unchanged — it already renders whatever is in the store; it is just
  populated on load now.

---

## Workstream 2 — Incremental + concurrent classification (also delivers granularity)

`refresh_clusters` keeps its sync signature and drives an `asyncio.run(...)`
internally, mirroring `tailor/service.py` and `discovery/pipeline.py`.

1. **Delta.** `T = collect_target_skill_tokens(session)`; load existing
   `ClusterMap`; `delta = T − set(aliases.keys())`. If `delta` is empty: skip all
   LLM calls, prune, save, done (near-instant warm path).
2. **Canonicalize the delta concurrently.** Shard `delta` into batches of size `B`
   (new `Settings` knob; default e.g. 60). Each batch is an async call receiving
   *the batch tokens + all existing canonical tokens as context*, so a new `"k8s"`
   can map onto an existing `"kubernetes"`. Fan out with `gather_isolated` +
   `asyncio.Semaphore(llm_concurrency)`. **Each batch completion = one progress step.**
3. **Reconcile pass.** One canonicalize over
   `{new canonical reps} ∪ {existing canonicals}` to merge cross-batch synonyms that
   cold-start sharding could split. Cheap (few reps); effectively a no-op on warm
   small deltas. **One progress step.**
4. **Theme the new canonicals concurrently.** Shard the newly-canonical tokens
   (those not already themed); each async call gets *existing theme labels+members
   as context* → assign to an existing theme or propose a new one. `gather_isolated`.
   `themes_to_pairs` already tolerates the many-to-one / leftover cases.
   **Each batch = one progress step.**
5. **Merge → prune → save.** `merge_cluster_map(existing, proposed)` (protects prior
   canonicals), then **drop any `aliases` / `theme_of` entry whose token ∉ T, and any
   `theme_label` left with no members** (decision 5 prune), then `save_cluster_map`.

**Progress math.** `begin(n_canon_batches + 1 + n_theme_batches)` computed up front;
`reporter.step()` per batch; `reporter.checkpoint()` between batches for cooperative
cancellation. Size `B` so a single batch stays under ~1 minute → satisfies the
"< 1 min per stage" guarantee (decision 4).

**New agent prompts.** Two incremental instruction variants are needed (the current
ones assume a full global set):

- *Incremental canonicalize:* "Here are NEW tokens and a list of EXISTING canonical
  tokens. Map each new token to an existing canonical when it is a true synonym;
  otherwise cluster it among the new tokens. Never rewrite or invent tokens."
- *Incremental theme:* "Here are NEW canonical tokens and the EXISTING themes
  (label → members). Assign each new token to an existing theme when it fits;
  otherwise propose a new theme. Preserve tokens byte-for-byte."

The existing whole-set prompts remain valid for the cold-start path (no existing
canonicals/themes), or the incremental prompts degrade naturally when the existing
sets are empty.

---

## Workstream 3 — Progress granularity

Delivered entirely by Workstream 2: the per-batch + reconcile steps give the
sub-minute cadence for clustering. **No other run kind is touched** (decision 4) —
pull/tailor/discover already emit per-job `current/total`.

---

## Error handling

- **Per-batch LLM failure (decision 6):** `gather_isolated` is ordered and
  error-isolated. A failed batch leaves *its* tokens unclassified this round (they
  stay their own canonical and fall to the `Other` theme via the existing
  `themes_to_pairs` catch-all) and reappear in the next delta. The run still
  completes successfully — matching the discovery/tailor "skip a failed job, retry
  next run" ethos. This replaces today's all-or-nothing abort.
- **Existing-canonical context (decision 7):** v1 passes all existing canonicals.
  On a mature map this prompt can grow; relevance-capping (prefix/embedding nearest)
  is noted as a future refinement, not built now.
- **`GET /api/runs`:** skips unreadable/parsing-failed files (tolerant
  `read_progress`).
- **Rehydrate fetch failure:** non-fatal; the bar simply stays empty.

---

## Testing (all offline — agents and browser are faked)

**Backend**
- `RunManager.list_active`: a directory mixing terminal and non-terminal files
  returns only the non-terminal ones, sorted.
- `GET /api/runs`: returns active runs; OpenAPI/TS drift gate regenerated and green.
- Delta computation: warm refresh with all tokens already mapped issues ~0 LLM
  calls; a delta of N tokens shards into the expected batch count.
- Concurrent batching: a fake `Runner` records call count == canon batches +
  reconcile + theme batches; reconcile merges a deliberately cross-batch synonym.
- Stale-token prune: a token removed from all target jobs is dropped from
  `aliases` / `theme_of`, and an emptied theme label is removed.
- Batch-failure tolerance: a fake `Runner` that raises on one batch still yields a
  completed run; the failed batch's tokens remain unclassified and reappear next
  delta.
- Progress: step count equals the computed total; cancellation surfaces at a
  between-batch checkpoint.

**Frontend**
- Mount → mocked `GET /api/runs` → store populated and `watchRun` called once per
  active run, with no double-subscribe when a run was also launched in-session.

---

## Out of scope (explicitly)

- New dedicated Runs dashboard page or run history (decision 1/2).
- Re-granularizing pull/tailor/discover/cover-letters/etc. (decision 4).
- A full "rebuild from scratch" classification path (decision 5).
- Relevance-capping the canonical context (decision 7).
