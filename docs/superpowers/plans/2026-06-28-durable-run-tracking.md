# Durable Run Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make in-flight run progress survive a page refresh by adding a `GET /api/runs` list endpoint and rehydrating the run bar (re-attaching SSE) on app mount.

**Architecture:** The backend already persists one JSON record per run under `data/runs/` and keeps the worker running across HTTP requests; only the frontend state was ephemeral. We add `RunManager.list_active()` + a `GET /api/runs` endpoint returning the non-terminal records, then a `useRehydrateRuns()` hook that fetches them on mount, seeds the Zustand store, and calls the existing `watchRun` SSE subscription for each.

**Tech Stack:** FastAPI + Pydantic (`CamelModel`), the existing `ProgressReporter`/`read_progress` file channel, React + Zustand + `@tanstack/react-query`, `openapi-fetch` typed client, MSW + Vitest for the frontend, `pytest` + `TestClient` for the backend.

## Global Constraints

- Tests run offline: `.venv/Scripts/python.exe -m pytest` and the web suite under `web/`. No API key or network.
- Wire format is **camelCase** (`CamelModel` with `alias_generator=to_camel`); Python stays snake_case.
- The OpenAPI → TS contract is a drift gate: after any schema/route change run `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` must pass.
- "Active" / non-terminal run states are exactly `state not in ("done", "error", "cancelled")` (i.e. `pending`, `running`, `cancelling`).
- Scope: **active runs only**, no history, no new dashboard page. The existing `RunPanel` is unchanged.
- Commit messages end with the repo's required trailers (`Co-Authored-By:` and `Claude-Session:` — copy from a recent commit).

---

### Task 1: `RunManager.list_active()`

**Files:**
- Modify: `src/resume_agent/api/runs/manager.py` (add method + a module constant near the top of the class region)
- Test: `tests/api/test_run_manager.py` (append tests)

**Interfaces:**
- Consumes: existing `read_progress(process, root)` from `resume_agent.progress`, already imported in `manager.py`.
- Produces: `RunManager.list_active(self) -> list[dict]` — every non-terminal run record, each guaranteed to carry `record["process"] == <run_id>` (the file stem), sorted ascending by `started_at`.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_run_manager.py`:

```python
def test_list_active_returns_only_non_terminal_sorted_by_started_at(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    # A finished run (InlineExecutor runs it to "done").
    mgr.submit("discover", lambda reporter: {"ok": True})

    # Two seeded-but-unfinished runs with explicit started_at ordering.
    import json
    for run_id, started in (("bbb", "2026-06-28T10:00:01"), ("aaa", "2026-06-28T10:00:00")):
        (tmp_path / f"{run_id}.json").write_text(
            json.dumps({
                "process": run_id, "kind": "pull", "state": "running",
                "label": "working", "current": 1, "total": 5,
                "started_at": started, "updated_at": started,
            }),
            encoding="utf-8",
        )

    active = mgr.list_active()
    ids = [r["process"] for r in active]
    assert ids == ["aaa", "bbb"]  # sorted by started_at, terminal run excluded
    assert all(r["state"] not in ("done", "error", "cancelled") for r in active)


def test_list_active_is_empty_when_root_missing(tmp_path):
    mgr = RunManager(root=tmp_path / "nope", executor=InlineExecutor())
    assert mgr.list_active() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py::test_list_active_returns_only_non_terminal_sorted_by_started_at -v`
Expected: FAIL with `AttributeError: 'RunManager' object has no attribute 'list_active'`

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/api/runs/manager.py`, add a module-level constant just below the imports:

```python
_TERMINAL_STATES = ("done", "error", "cancelled")
```

Add this method to `RunManager` (e.g. directly after `get`):

```python
def list_active(self) -> list[dict]:
    """Every non-terminal run record, sorted by ``started_at`` ascending.

    Reads the same per-run JSON files the worker writes, so progress survives a
    client refresh: the bar is rehydrated from here. Terminal runs
    (done/error/cancelled) are omitted; unreadable files are skipped.
    """
    if not self.root.exists():
        return []
    records: list[dict] = []
    for path in self.root.glob("*.json"):
        record = read_progress(path.stem, root=self.root)
        if record is None:
            continue
        if str(record.get("state") or "running") in _TERMINAL_STATES:
            continue
        record.setdefault("process", path.stem)
        records.append(record)
    records.sort(key=lambda r: str(r.get("started_at") or ""))
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v`
Expected: PASS (all, including the two new tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/runs/manager.py tests/api/test_run_manager.py
git commit -m "feat: add RunManager.list_active for run rehydration"
```

---

### Task 2: `GET /api/runs` endpoint + contract regen

**Files:**
- Modify: `src/resume_agent/api/routers/runs.py` (add endpoint above `get_run`)
- Create: `tests/api/test_runs_list.py`
- Regenerate: `contracts/openapi.json`, `contracts/ts/api.ts`

**Interfaces:**
- Consumes: `RunManager.list_active()` (Task 1); existing `record_to_run(run_id, record)` and `RunOut` schema.
- Produces: `GET /api/runs -> list[RunOut]` (active runs only). In the generated TS client this is `paths["/api/runs"]["get"]`, callable as `api.GET("/api/runs")`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_runs_list.py`:

```python
"""GET /api/runs returns active (non-terminal) runs for client rehydration."""

from concurrent.futures import Future

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def test_list_runs_returns_active_runs(monkeypatch):
    # Keep a launched run non-terminal: a manager whose executor never starts work.
    import resume_agent.api.app as app_module
    from resume_agent.api.runs.manager import RunManager

    class _NeverRuns:
        def submit(self, fn, /, *args, **kwargs):
            return Future()  # pending forever

        def shutdown(self, wait=False):
            pass

    def factory(*args, **kwargs):
        kwargs["executor"] = _NeverRuns()
        return RunManager(*args, **kwargs)

    monkeypatch.setattr(app_module, "RunManager", factory)

    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        launched = client.post("/api/discover").json()
        run_id = launched["runId"]

        runs = client.get("/api/runs").json()

    assert isinstance(runs, list)
    ids = [r["runId"] for r in runs]
    assert run_id in ids
    row = next(r for r in runs if r["runId"] == run_id)
    assert row["kind"] == "discover"
    assert row["state"] not in ("done", "error", "cancelled")


def test_list_runs_empty_when_nothing_launched():
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        assert client.get("/api/runs").json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_list.py -v`
Expected: FAIL with `404` on `GET /api/runs` (route not defined)

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/api/routers/runs.py`, add this endpoint immediately **above** the existing `@router.get("/runs/{run_id}", ...)` handler:

```python
@router.get("/runs", response_model=list[RunOut])
def list_runs(mgr: RunManager = Depends(get_run_manager)):
    """Active (non-terminal) runs, so a refreshed client can rehydrate its bar."""
    return [record_to_run(str(r.get("process") or ""), r) for r in mgr.list_active()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_list.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the contract and verify the drift gate**

Run:
```bash
bash scripts/gen_ts_client.sh
.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v
```
Expected: `contracts/openapi.json` and `contracts/ts/api.ts` now include the `/api/runs` GET path; the contract test PASSES.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/routers/runs.py tests/api/test_runs_list.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: add GET /api/runs list endpoint"
```

---

### Task 3: Rehydrate the run bar on mount

**Files:**
- Modify: `web/src/lib/runs/sse.ts` (export a shared `stateToStatus` helper; reuse it inside `watchRun`)
- Create: `web/src/features/runs/use-rehydrate-runs.ts`
- Modify: `web/src/app/AppLayout.tsx` (call the hook once)
- Create: `web/src/features/runs/use-rehydrate-runs.test.tsx`

**Interfaces:**
- Consumes: `GET /api/runs` typed as `api.GET("/api/runs")` (Task 2); existing `watchRun(runId, kind, onDone?)`, `useRunStore`, `unwrap`.
- Produces: `stateToStatus(state: string): RunRecord["status"]` exported from `web/src/lib/runs/sse.ts`; `useRehydrateRuns(): void` exported from `web/src/features/runs/use-rehydrate-runs.ts`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/runs/use-rehydrate-runs.test.tsx`:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";
import { useRehydrateRuns } from "./use-rehydrate-runs";

const watchRun = vi.fn();
vi.mock("@/lib/runs/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/runs/sse")>();
  return { ...actual, watchRun: (...args: unknown[]) => watchRun(...args) };
});

beforeEach(() => {
  watchRun.mockReset();
  useRunStore.setState({ runs: {} });
});

it("seeds the store and watches each active run on mount", async () => {
  server.use(
    http.get("/api/runs", () =>
      HttpResponse.json([
        {
          runId: "r1",
          kind: "pull",
          state: "running",
          label: "Pulling",
          percent: 40,
          current: 2,
          total: 5,
          etaText: "~1m left",
          result: null,
          error: null,
        },
      ]),
    ),
  );

  renderHook(() => useRehydrateRuns());

  await waitFor(() => expect(useRunStore.getState().runs.r1).toBeDefined());
  expect(useRunStore.getState().runs.r1.status).toBe("running");
  expect(useRunStore.getState().runs.r1.percent).toBe(40);
  expect(watchRun).toHaveBeenCalledWith("r1", "pull");
});

it("does not re-subscribe to a run already in the store", async () => {
  useRunStore.setState({
    runs: {
      r1: {
        runId: "r1",
        kind: "pull",
        status: "running",
        percent: 10,
        phase: "",
        current: 0,
        total: 0,
        etaText: null,
      },
    },
  });
  server.use(
    http.get("/api/runs", () =>
      HttpResponse.json([
        { runId: "r1", kind: "pull", state: "running", label: "", percent: 10, current: 0, total: 0, etaText: null, result: null, error: null },
      ]),
    ),
  );

  renderHook(() => useRehydrateRuns());

  // Give the effect a tick; the run was already present, so no new subscription.
  await new Promise((r) => setTimeout(r, 20));
  expect(watchRun).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run src/features/runs/use-rehydrate-runs.test.tsx`
Expected: FAIL — module `./use-rehydrate-runs` does not exist.

- [ ] **Step 3a: Export the shared status mapper from `sse.ts`**

In `web/src/lib/runs/sse.ts`, add this exported function above `watchRun`:

```ts
/** Map a backend run `state` to the store's `status`. */
export function stateToStatus(state: string): RunRecord["status"] {
  switch (state) {
    case "done":
      return "succeeded";
    case "error":
      return "failed";
    case "cancelled":
      return "cancelled";
    case "cancelling":
      return "cancelling";
    case "pending":
      return "queued";
    default:
      return "running";
  }
}
```

Then replace the inline mapping inside `watchRun.onmessage` — change:

```ts
    const state = data.state ?? "running";
    const status: RunRecord["status"] =
      state === "done"
        ? "succeeded"
        : state === "error"
          ? "failed"
          : state === "cancelled"
            ? "cancelled"
            : state === "cancelling"
              ? "cancelling"
              : state === "pending"
                ? "queued"
                : "running";
```

to:

```ts
    const state = data.state ?? "running";
    const status: RunRecord["status"] = stateToStatus(state);
```

- [ ] **Step 3b: Create the rehydrate hook**

Create `web/src/features/runs/use-rehydrate-runs.ts`:

```ts
import { useEffect, useRef } from "react";

import { api, unwrap } from "@/lib/api/client";
import { stateToStatus, watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";

/**
 * On first mount, fetch active runs (GET /api/runs) and re-attach the SSE bar so
 * a page refresh does not lose in-flight progress. Runs already in the store
 * (e.g. launched this session) are skipped to avoid a double subscription.
 */
export function useRehydrateRuns(): void {
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    void (async () => {
      let runs: Awaited<ReturnType<typeof fetchActive>>;
      try {
        runs = await fetchActive();
      } catch {
        return; // non-fatal: the bar simply stays empty
      }
      for (const r of runs) {
        if (useRunStore.getState().runs[r.runId]) continue;
        useRunStore.getState().upsert({
          runId: r.runId,
          kind: r.kind,
          status: stateToStatus(r.state),
          percent: r.percent ?? 0,
          phase: r.label ?? "",
          current: r.current ?? 0,
          total: r.total ?? 0,
          etaText: r.etaText ?? null,
        });
        watchRun(r.runId, r.kind);
      }
    })();
  }, []);
}

async function fetchActive() {
  return await unwrap(api.GET("/api/runs"));
}
```

- [ ] **Step 3c: Call the hook in `AppLayout`**

In `web/src/app/AppLayout.tsx`, add the import:

```tsx
import { useRehydrateRuns } from "@/features/runs/use-rehydrate-runs";
```

and call it as the first line inside `export function AppLayout() {`:

```tsx
export function AppLayout() {
  useRehydrateRuns();
  return (
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `web/`): `npx vitest run src/features/runs/use-rehydrate-runs.test.tsx src/lib/runs/sse.test.ts`
Expected: PASS (the new hook tests and the existing SSE tests still green after the refactor).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/runs/sse.ts web/src/features/runs/use-rehydrate-runs.ts web/src/features/runs/use-rehydrate-runs.test.tsx web/src/app/AppLayout.tsx
git commit -m "feat: rehydrate run bar from GET /api/runs on mount"
```

---

## Self-Review

**Spec coverage (Workstream 1 of the design):**
- `RunManager.list_active()` + `GET /api/runs` (active only) → Tasks 1–2. ✓
- Contract regen + drift gate → Task 2 Step 5. ✓
- Mount rehydrate + SSE re-attach + no double-subscribe → Task 3. ✓
- `RunPanel` unchanged → not modified anywhere. ✓
- "Active only" filter `state not in (done, error, cancelled)` → `_TERMINAL_STATES` in Task 1. ✓

**Type consistency:** `list_active() -> list[dict]` (Task 1) is consumed in Task 2 via `r.get("process")` and `record_to_run`. `stateToStatus` (Task 3a) is reused by both `watchRun` and the hook (3b). `api.GET("/api/runs")` exists only after Task 2's regen — Task 3 depends on Task 2. ✓

**Placeholder scan:** none — every step shows complete code/commands.
