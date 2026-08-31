# Durable Run Tracking Implementation Plan

> **For agentic workers:** implement task-by-task with tests first. Check off each
> step only after its verification command passes.

**Goal:** Preserve tracking across browser refresh without presenting malformed or
orphaned work as active.

**Architecture:** `RunManager` parses the JSON channel into typed `RunSnapshot`s,
owns startup recovery and singleton submission, and exposes active snapshots. The
HTTP adapter returns the repository's standard paginated envelope. A frontend run
tracker owns SSE connection identity; the Zustand store remains a projection, not
the subscription registry.

**Design source:**
`docs/superpowers/specs/2026-06-28-durable-run-tracking-and-incremental-classification-design.md`

## Global constraints

- Single backend process per `RUNS_ROOT`; worker resume after restart is out of
  scope.
- Active states are exactly `pending`, `running`, and `cancelling`.
- Terminal states are exactly `done`, `error`, and `cancelled`.
- Raw JSON dictionaries do not cross the `RunManager` interface.
- List endpoints use `Page[...]`, `Pagination`, `paginate`, and `to_page` already in
  the repository.
- Wire names are camelCase through `CamelModel`.
- SSE transport errors are not run failures.
- Tests are offline. Regenerate OpenAPI and TypeScript after route/schema changes.

---

### Task 1: Add typed run snapshots and strict tolerant parsing

**Files**

- Create: `src/resume_tailor_harness/api/runs/models.py`
- Modify: `src/resume_tailor_harness/api/runs/manager.py`
- Modify: `src/resume_tailor_harness/api/runs/sse.py`
- Test: `tests/api/test_run_manager.py`
- Test: `tests/api/test_runs_sse.py`

**Interface**

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
    phase_index: int | None = None
    phase_count: int | None = None

def parse_run_snapshot(run_id: str, raw: object) -> RunSnapshot | None: ...
```

Parsing rules:

- `run_id` always comes from the requested ID/file stem. Ignore a mismatched raw
  `process` field.
- Require a nonblank `kind` and a known `RunState`.
- Require nonnegative integer `current`/`total`; reject booleans.
- Require parseable timezone-aware phase `started_at` and `updated_at`.
- Add immutable `created_at` when a run is created. Preserve it through every
  `RunProgressReporter.begin`; for legacy records only, fall back to the first
  available `started_at`.
- Normalize label/error only as documented; do not silently reinterpret an unknown
  state as `running`.
- Preserve JSON-safe `result` as opaque data.

- [ ] Write tests for every accepted state and every rejection rule above.
- [ ] Add `parse_run_snapshot` and `RunSnapshot`.
- [ ] Refactor `RunManager.get(run_id)` to return `RunSnapshot | None`; keep a
      private `_read_record` only for state-transition writes.
- [ ] Refactor `record_to_run` to consume `RunSnapshot`, deriving percentage/ETA
      without exposing a persistence dictionary.
- [ ] Update existing route/SSE tests and callers for the typed interface.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py tests/api/test_runs_sse.py -v
```

Expected: all snapshot, route-projection, cancellation, and SSE tests pass.

---

### Task 2: List active runs and recover interrupted runs

**Files**

- Modify: `src/resume_tailor_harness/api/runs/manager.py`
- Modify: `src/resume_tailor_harness/api/app.py`
- Test: `tests/api/test_run_manager.py`

**Interfaces**

```python
def list_active(self) -> list[RunSnapshot]: ...
def recover_interrupted(self) -> int: ...
```

`list_active`:

- scans `root/*.json` through the same snapshot parser as `get`;
- includes only the explicit active-state allowlist;
- skips absent, unreadable, or invalid records;
- sorts by `(snapshot.created_at, snapshot.run_id)`; phase transitions must not
  reorder active runs.

`recover_interrupted`:

- runs once in application lifespan before `sweep` and before accepting traffic;
- changes every valid pre-existing active record to `error`;
- sets a stable user-facing label such as `Interrupted` and a non-sensitive error
  such as `Backend restarted before this run completed`;
- preserves progress and result fields, updates `updated_at`, and uses the atomic
  writer;
- leaves terminal and invalid files unchanged.

- [ ] Test mixed active/terminal/corrupt files, identical creation timestamps, a
      stored process ID that disagrees with the file stem, and a phase transition that
      changes `started_at` without changing list order.
- [ ] Test that startup recovery returns its changed count and makes all recovered
      records terminal.
- [ ] Test that a recovered record is not returned by `list_active`.
- [ ] Implement and call `recover_interrupted()` before `sweep()` in lifespan.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py tests/api/test_app_health.py -v
```

---

### Task 3: Add singleton run submission

This prevents two refresh-cluster launches from occupying worker threads while one
waits on the classification file lock.

**Files**

- Modify: `src/resume_tailor_harness/api/runs/manager.py`
- Test: `tests/api/test_run_manager.py`

**Interface change (additive)**

```python
def submit(
    self,
    kind: str,
    fn: RunFn,
    *,
    singleton_key: str | None = None,
) -> str: ...
```

Rules:

- no key preserves current behavior;
- a key with an active in-process run returns that run ID without submitting work;
- key lookup and pre-registration are atomic under one manager `RLock`; register
  before calling `executor.submit`, because an executor may run inline;
- never wait for worker completion while holding the lock, and roll registration
  back if `executor.submit` itself raises;
- terminal completion, cancellation-before-start, and submission failure release
  the key;
- different keys and unkeyed work remain independent;
- do not infer singleton state by scanning files on every submit.

- [ ] Test a race with two threads submitting the same key: one work callable runs
      and both calls return the same ID.
- [ ] Test the existing `InlineExecutor` path does not deadlock and releases the
      key before `submit` returns.
- [ ] Test key release after done, error, and queued cancellation.
- [ ] Test different keys still run independently.
- [ ] Implement without changing existing launch call sites.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v
```

---

### Task 4: Add the paginated active-runs endpoint

**Files**

- Modify: `src/resume_tailor_harness/api/schemas/runs.py`
- Modify: `src/resume_tailor_harness/api/routers/runs.py`
- Create: `tests/api/test_runs_list.py`
- Regenerate: `contracts/openapi.json`, `contracts/ts/api.ts`

**HTTP contract**

```http
GET /api/runs?page=1&pageSize=100
```

Response: `Page[RunOut]` using the existing shape:

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "pageSize": 100,
    "totalItems": 0,
    "totalPages": 0
  }
}
```

Contract details:

- `page: int = Query(1, ge=1)`;
- `pageSize: int = Query(100, ge=1, le=200)`;
- `RunOut.state` uses `RunState`, not unconstrained `str`;
- add the static `/runs` route before `/runs/{run_id}`;
- map snapshots to `RunOut`, paginate with the shared helper, and return `Page[RunOut]`;
- auth and the standard error envelope come from existing router/app wiring.

- [ ] Test page metadata, deterministic ordering, active-only filtering, camelCase,
      invalid query validation, and auth when configured.
- [ ] Implement the endpoint with shared pagination modules.
- [ ] Regenerate and verify contracts.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_runs_list.py tests/api/test_openapi_contract.py -v
bash scripts/gen_ts_client.sh
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v
```

The first drift-gate run should fail before generation and pass afterward.

---

### Task 5: Deepen frontend connection ownership into a run tracker

**Files**

- Modify: `web/src/lib/runs/sse.ts`
- Create: `web/src/lib/runs/tracker.ts`
- Create: `web/src/lib/runs/tracker.test.ts`
- Modify: `web/src/features/runs/use-launch-run.ts`
- Modify: existing SSE tests

**Interfaces**

```ts
export function stateToStatus(state: RunState): RunRecord["status"];
export function trackRun(
  seed: RunSeed,
  onDone?: (run: RunRecord) => void,
): void;
export function isTracking(runId: string): boolean;
export function resetRunTrackerForTests(): void;
```

Implementation rules:

- `sse.ts` remains the transport adapter and returns an unsubscribe function.
- `tracker.ts` owns a `Map<runId, subscription>` and completion callbacks.
- Repeated `trackRun` for the same ID does not create another `EventSource`; it may
  add a completion callback.
- Terminal messages close/delete the subscription before invoking callbacks.
- A transport `onerror` does not write `status: "failed"`. Reconcile once through
  `GET /api/runs/{run_id}`; update terminal state if the backend is terminal,
  otherwise allow a bounded reconnect. Only a backend `state: "error"` means the
  run failed.
- `useLaunchRun` upserts the launch response and calls `trackRun`; it no longer
  calls `watchRun` directly.

- [ ] Add tests for dedupe, callback fan-out, registry cleanup, transient transport
      error, backend-terminal reconciliation, and reset cleanup.
- [ ] Export the status mapper and keep unknown values impossible at the typed
      contract; defensively map runtime unknowns to `running` only in the transport
      parser.
- [ ] Refactor launch tracking.

Run from `web/`:

```powershell
npx vitest run src/lib/runs/sse.test.ts src/lib/runs/tracker.test.ts src/features/runs/use-launch-run.test.tsx
```

---

### Task 6: Rehydrate all active pages on app mount

**Files**

- Create: `web/src/features/runs/use-rehydrate-runs.ts`
- Create: `web/src/features/runs/use-rehydrate-runs.test.tsx`
- Modify: `web/src/app/AppLayout.tsx`

Behavior:

- fetch all pages with `pageSize=200` using the existing `fetchAllPages` helper;
- for each server snapshot, always upsert its latest progress into the store;
- call `trackRun` for every item and let the tracker deduplicate;
- do not use store membership as a subscription test;
- use an `AbortController`/cancelled flag so a late list response does not mutate an
  unmounted tree;
- let the query/client retry policy perform one retry; otherwise fail silently and
  keep the rest of the application usable;
- call the hook once from `AppLayout`.

- [ ] Test multiple pages, latest-snapshot overwrite, existing-store-but-not-tracked,
      already-tracked dedupe, React Strict Mode/remount, fetch failure, and unmount
      before response.
- [ ] Implement the hook and mount it.

Run from `web/`:

```powershell
npx vitest run src/features/runs/use-rehydrate-runs.test.tsx src/lib/runs/tracker.test.ts
```

---

### Task 7: Full verification

- [ ] Backend focused suite:

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py tests/api/test_runs_sse.py tests/api/test_runs_list.py tests/api/test_openapi_contract.py -v
```

- [ ] Full backend suite:

```powershell
.venv/Scripts/python.exe -m pytest
```

- [ ] Frontend run suite and type/build checks:

```powershell
Set-Location web
npx vitest run src/lib/runs src/features/runs
npm run build
```

- [ ] Manual smoke test: launch a run, refresh the page, confirm one network SSE
      connection for that run, then confirm terminal cleanup.
- [ ] Manual restart test: stop the backend during a run, restart it, and confirm
      the old record is terminal rather than rehydrated as active.

## Review corrections captured

- Replaced `record.setdefault("process", stem)` with a typed parser whose ID is
  authoritative.
- Replaced terminal-negation filtering with an explicit active-state allowlist.
- Replaced unchecked phase-time sorting with immutable parsed creation time and an
  ID tiebreaker.
- Prevented ghost-active records after backend restart.
- Reused the existing pagination interface instead of creating an unbounded list
  contract.
- Replaced store-based SSE dedupe with actual connection ownership.
- Stopped converting transport failure into backend run failure.
