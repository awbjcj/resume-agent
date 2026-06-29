# Durable run tracking + incremental skill classification — Design

**Date:** 2026-06-28
**Branch:** `feat/match-gap-dashboard-redesign`
**Status:** Revised after architecture, interface, correctness, and performance review

## Problem

1. A page refresh loses the browser's in-memory run list and SSE subscriptions even
   though the worker and its JSON progress record still exist.
2. Skill-cluster refresh reports two opaque steps because each phase is one large
   LLM call.
3. Every refresh reclassifies the complete token set, so the warm path repeats
   expensive work.

The features are coupled: useful progress requires breaking classification into
bounded calls, and bounded calls make incremental reuse and concurrency possible.

## Scope and operating assumptions

- Run rehydration means **browser refresh in the same backend process**. Work is not
  resumed after a backend restart.
- The file-backed run substrate supports one backend process for a given
  `RUNS_ROOT`. Multi-process ownership would require a database/queue and is out of
  scope.
- The run bar shows active runs only. History and a dedicated runs page remain out
  of scope.
- Only skill classification gains new progress granularity.
- Existing canonical choices remain stable. New tokens may map to them, but an
  incremental refresh does not rewrite them.

## Settled decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Run surface | Rehydrate the existing top bar |
| 2 | Run list | Active-only, paginated with the repository's standard `Page` envelope |
| 3 | Stored-run interface | Parse raw JSON into a typed `RunSnapshot` inside `RunManager` |
| 4 | Restart behavior | Mark pre-existing non-terminal files interrupted on startup; never present ghost-active work |
| 5 | Subscription ownership | A process-wide frontend run tracker owns and deduplicates SSE connections |
| 6 | Classification strategy | Incremental concurrent alias batches, one global reconcile, then concurrent theme batches |
| 7 | Retry representation | Missing alias/theme entries are the backlog; never persist failure fallbacks |
| 8 | Canonical batch failure | Keep successful token assignments; omit failed tokens so they retry next refresh |
| 9 | Reconcile failure | Fatal and transactional; keep the last-good cluster map so the whole delta retries |
| 10 | Theme batch failure | Keep successful assignments; omit failed themes so they retry next refresh |
| 11 | Existing context | Pass all stable existing canonicals/themes in v1 and measure prompt growth |
| 12 | Duplicate refresh | The run manager coalesces concurrent refresh-cluster launches by singleton key |

## Architecture

### Run tracking module

`RunManager` remains the deep module for run ownership. Its interface exposes typed
snapshots and run lifecycle operations; callers do not inspect persistence-shaped
dictionaries.

```python
class RunState(StrEnum):
    pending = "pending"
    running = "running"
    cancelling = "cancelling"
    done = "done"
    error = "error"
    cancelled = "cancelled"

@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    kind: str
    state: RunState
    label: str
    current: int
    total: int
    created_at: datetime
    phase_started_at: datetime
    updated_at: datetime
    result: object | None
    error: str | None

class RunManager:
    def get(self, run_id: str) -> RunSnapshot | None: ...
    def list_active(self) -> list[RunSnapshot]: ...
    def submit(
        self,
        kind: str,
        fn: RunFn,
        *,
        singleton_key: str | None = None,
    ) -> str: ...
```

The implementation may still use the existing atomic JSON channel. Parsing is
tolerant at the file seam but strict about the interface:

- file stem is authoritative for `run_id`;
- active states are the explicit allowlist `pending`, `running`, `cancelling`;
- unknown state, blank kind, invalid counters, or invalid timestamps make a record
  unreadable and therefore omitted from the list;
- `created_at` is immutable run creation time; `phase_started_at` is the current
  progress phase's ETA clock. Legacy records without `created_at` fall back to
  their available `started_at` value and gain `created_at` on the next write;
- ordering is `(created_at, run_id)`, not phase time or lexical comparison of
  unchecked strings.

At application startup, before normal traffic, `recover_interrupted()` changes all
pre-existing non-terminal records to terminal `error` with an interruption message.
This avoids claiming a dead worker is active after a process restart.

`GET /api/runs?page=1&pageSize=100` returns `Page[RunOut]`, using the existing
pagination schema and mapper. `RunOut.state` is the same `RunState` enum, so the
wire contract documents the complete state set. Route errors continue to use the
repository's standard error envelope.

### Frontend run tracker

Store membership is not proof of an SSE subscription. A process-wide tracker owns
the connection registry:

```ts
trackRun(run: RunSeed, onDone?: (run: RunRecord) => void): void
isTracking(runId: string): boolean
resetRunTrackerForTests(): void
```

Launching and rehydrating both call `trackRun`. Rehydration always upserts the
server snapshot, then asks the tracker to attach; the tracker, not the Zustand
store, deduplicates by `runId`. Completion removes the registry entry. A transport
error is not converted into a failed run: reconnect or reconcile with
`GET /api/runs/{id}` before changing terminal state.

### Incremental skill-classification module

Create `resume_agent.taxonomy.classification` as the deep module that owns delta
planning, batching, model-output projection, reconcile, theme reuse, progress, and
failure accounting. The match-gap application module supplies demanded tokens and
persists the returned additions; it does not know batch mechanics.

```python
@dataclass(frozen=True)
class ClassificationFailure:
    phase: Literal["canonicalize", "theme"]
    tokens: tuple[str, ...]
    message: str

@dataclass(frozen=True)
class ClassificationOutcome:
    additions: ClusterMap
    failures: tuple[ClassificationFailure, ...]
    canonical_batches: int
    theme_batches: int
    prompt_bytes: int
    elapsed_ms: int

async def classify_incrementally(
    *,
    demanded_tokens: set[str],
    existing: ClusterMap,
    canonicalizer: Runner,
    themer: Runner,
    batch_size: int,
    concurrency: int,
    reporter: ProgressReporter | None,
) -> ClassificationOutcome: ...
```

`Runner` is the real seam: production Agno and offline fakes are two adapters.
No new protocol is introduced around `classify_incrementally`. Current Agno
[batch documentation](https://github.com/agno-agi/docs/blob/main/use-cases/document-processing/batch-and-durability.mdx)
shows one agent used for concurrent `arun` calls behind a semaphore; these agents
have no database/session memory configured, so batches remain independent.

#### Delta and backlog

Given demanded tokens `T` and current map `M`:

```text
alias_delta   = T - M.aliases.keys()
theme_backlog = demanded canonical values after alias merge - M.theme_of.keys()
```

The second set is computed after successful alias results are known. This means a
theme batch that failed last run is retried even though its alias already exists.
A canonicalization failure does not write an identity alias; consumers already
fall back to identity for missing aliases, so the token remains visible and
`clusters_stale` remains true until retry succeeds.

#### Canonicalization and reconcile

1. Sort and shard `alias_delta`.
2. Run batches with `gather_isolated` and one shared semaphore.
3. Project each response against its authoritative batch and the stable existing
   canonical set. Persist only covered, valid token assignments. Missing,
   ambiguous, or invented members become per-token failures.
4. Reconcile only successful new heads against one another and existing stable
   canonicals.
5. If reconcile fails, raise and do not save. Otherwise rewrite successful batch
   assignments through the reconcile mapping.

The projector never chooses an arbitrary existing canonical from a malformed
cluster. A cluster containing multiple existing canonicals, or an existing
canonical in a position that contradicts the prompt contract, is rejected for its
new members.

#### Theming

Existing theme context includes both stable ID and display label:

```json
{"id": "cloud-infra", "label": "Cloud / Infrastructure", "skills": ["kubernetes"]}
```

Model output distinguishes reuse of an existing ID from proposal of a new label.
Projection validates that each successful token appears once and that reused IDs
exist. Missing or malformed assignments stay out of `theme_of` and retry next
run. There is no automatic `Other` fallback for a failed batch.

New theme IDs are allocated centrally after all batches finish. Equal normalized
labels merge; slug collisions receive deterministic suffixes (`cloud`, `cloud-2`)
without overwriting another label. Existing IDs and labels always win.

#### Apply, prune, and save

Under the existing refresh lock:

1. load current map;
2. classify outside any database transaction but inside the single refresh
   operation;
3. merge successful additions without redirecting stable existing canonicals;
4. prune alias source keys not in `T`, retain terminal self-maps required by
   surviving aliases, prune unused theme assignments and labels;
5. checkpoint cancellation;
6. atomically save once.

The refresh application module returns a JSON-safe summary with final counts,
failure counts, batch counts, prompt bytes, and elapsed time. It does not call
`reporter.done`; `RunManager` is the single owner of terminal run state.

## Progress contract

The number of theme batches is unknown until canonicalization and reconcile
finish, so one guessed total is incorrect. Use progress phases:

1. canonicalize — total is known alias-batch count;
2. reconcile — total 1 when needed;
3. theme — total is known after alias merge.

Each completed batch advances one step, including failed isolated batches. A
checkpoint runs while calls are in flight and before save. Empty phases are not
started. A fully warm run emits a short `Checking skill clusters` phase and makes
zero LLM calls.

## Performance contract

Optimization is measurement-led:

- record alias/theme token counts, batch counts, maximum in-flight calls, prompt
  bytes, and elapsed milliseconds in the result/test adapter;
- observe maximum in-flight calls through optional acquire/release callbacks inside
  `llm_runner.acall`, preserving leaf ownership of the semaphore;
- offline concurrency tests assert the observed maximum never exceeds
  `llm_concurrency` and exceeds one when at least two batches exist;
- warm path asserts zero model calls;
- a representative manual calibration records before/after cold and warm timing
  before changing the default batch size;
- the “under one minute per visible stage” target is an acceptance measurement,
  not a guarantee inferred from `batch_size=60`.

Passing all existing context has cost approximately
`O(number_of_batches × existing_context_size)`. V1 accepts this explicitly but
must expose prompt-byte measurements so relevance-capping can be justified with
data later.

## Error semantics

- Corrupt run file: skipped by list; single-run lookup behaves as not found.
- Backend restart: orphaned active record becomes terminal error at startup.
- Rehydrate list fetch failure: non-fatal; retry once through the query client.
- SSE transport failure: not a run failure; reconcile through the status endpoint.
- Canonical batch failure: partial success, failed tokens absent and retryable.
- Reconcile failure: run error, no cluster-map write.
- Theme batch failure: partial success, failed canonical tokens remain unthemed and
  retryable.
- Save failure or cancellation before save: run error/cancelled, last-good file
  remains intact.

## Verification

### Run tracking

- Typed parsing rejects unknown states and malformed timestamps/counters.
- File stem overrides a mismatched stored process ID.
- Active snapshots sort by parsed timestamp and run ID.
- Startup recovery terminalizes orphaned non-terminal records.
- `GET /api/runs` uses the standard page envelope and camelCase fields.
- Auth and standard error-envelope behavior remain unchanged.
- Rehydrate fetches every page, seeds the store, and creates one connection per
  run even under React Strict Mode/remount.
- A transient SSE error does not mark the run failed.

### Classification

- Warm map with no alias or theme backlog makes zero model calls.
- Failed canonical tokens are absent from aliases and retry next refresh.
- Failed theme tokens retain aliases but remain absent from `theme_of` and retry.
- Reconcile failure preserves the last-good file.
- Cross-batch synonyms reconcile correctly.
- Existing theme IDs are reused; slug collisions do not overwrite labels.
- Prune removes stale sources, unused terminals, theme assignments, and labels.
- Progress totals match each real phase; cancellation prevents save.
- Concurrency and prompt-growth metrics are asserted offline.

## Out of scope

- Resuming work after process restart.
- Multi-process run ownership.
- Run history UI.
- Reclassifying stable existing canonical choices.
- Relevance/embedding capping of existing context before measurements justify it.
