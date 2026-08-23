import { beforeEach, expect, it, vi } from "vitest";

import type { RunRecord } from "./store";

const mocks = vi.hoisted(() => ({ apiGet: vi.fn(), watchRun: vi.fn() }));
vi.mock("@/lib/api/client", () => ({
  api: { GET: mocks.apiGet },
  // Faithful to the real helpers rather than identity: the tracker reads runs
  // through fetchAllPages, so a stub that skipped the Page envelope would let
  // an envelope mistake pass here and fail only in the browser.
  unwrap: async (request: Promise<{ data?: unknown }>) => (await request).data,
  fetchAllPages: async (
    getPage: (page: number) => Promise<{ data?: unknown }>,
  ) => {
    const first = (await getPage(1)).data as {
      data: unknown[];
      pagination: { totalPages: number };
    };
    const all = [...first.data];
    for (let page = 2; page <= first.pagination.totalPages; page += 1) {
      const next = (await getPage(page)).data as { data: unknown[] };
      all.push(...next.data);
    }
    return all;
  },
}));
vi.mock("./sse", () => ({
  stateToStatus: (state: string) =>
    state === "done"
      ? "succeeded"
      : state === "error"
        ? "failed"
        : state === "cancelled"
          ? "cancelled"
          : "running",
  watchRun: mocks.watchRun,
}));

import {
  addTerminalListener,
  completeRuns,
  isTracking,
  pollRunsNow,
  resetRunTrackerForTests,
  stopRunPoller,
  trackRun,
} from "./tracker";
import { useRunStore } from "./store";

beforeEach(() => {
  resetRunTrackerForTests();
  mocks.watchRun.mockReset();
  mocks.watchRun.mockReturnValue(vi.fn());
  mocks.apiGet.mockReset();
});

it("owns one subscription per run and fans out completion callbacks", () => {
  const first = vi.fn();
  const second = vi.fn();
  trackRun({ runId: "r1", kind: "pull" }, first);
  trackRun({ runId: "r1", kind: "pull" }, second);

  expect(mocks.watchRun).toHaveBeenCalledOnce();
  expect(isTracking("r1")).toBe(true);

  const onDone = mocks.watchRun.mock.calls[0][2] as (run: RunRecord) => void;
  const completed = {
    runId: "r1",
    kind: "pull",
    status: "succeeded",
    percent: 100,
    phase: "Done",
    current: 1,
    total: 1,
    etaText: null,
  } satisfies RunRecord;
  onDone(completed);

  expect(first).toHaveBeenCalledWith(completed);
  expect(second).toHaveBeenCalledWith(completed);
  expect(isTracking("r1")).toBe(false);
});

it("reset closes active subscriptions", () => {
  const unsubscribe = vi.fn();
  mocks.watchRun.mockReturnValue(unsubscribe);
  trackRun({ runId: "r1", kind: "pull" });

  resetRunTrackerForTests();

  expect(unsubscribe).toHaveBeenCalledOnce();
  expect(isTracking("r1")).toBe(false);
});

it("reconciles a terminal backend status after an SSE transport error", async () => {
  const onDone = vi.fn();
  mocks.apiGet.mockResolvedValue({
    data: {
      data: [
        {
          runId: "r1",
          kind: "pull",
          state: "done",
          label: "Done",
          percent: 100,
          current: 1,
          total: 1,
          etaText: null,
          result: null,
          error: null,
          meta: { jobIds: [3, 8] },
        },
      ],
      pagination: { totalPages: 1 },
    },
    error: undefined,
  });
  trackRun({ runId: "r1", kind: "pull" }, onDone);

  const onTransportError = mocks.watchRun.mock.calls[0][3] as () => void;
  onTransportError();

  await vi.waitFor(() => expect(onDone).toHaveBeenCalledOnce());
  expect(onDone.mock.calls[0][0].status).toBe("succeeded");
  expect(onDone.mock.calls[0][0].meta).toEqual({ jobIds: [3, 8] });
  expect(mocks.watchRun).toHaveBeenCalledOnce();
  expect(isTracking("r1")).toBe(false);
});

it("runs one lifecycle for a completion and removes it after the display window", () => {
  vi.useFakeTimers();
  useRunStore.setState({ runs: {} });
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));

  const finished = {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "Done",
    current: 1,
    total: 1,
    etaText: null,
  } satisfies RunRecord;
  completeRuns([finished]);

  expect(seen).toEqual([[finished]]);
  expect(useRunStore.getState().runs.r1?.percent).toBe(100);

  vi.advanceTimersByTime(4000);
  expect(useRunStore.getState().runs.r1).toBeUndefined();
  vi.useRealTimers();
});

it("announces a completion exactly once even if two paths report it", () => {
  useRunStore.setState({ runs: {} });
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));
  const finished = {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "Done",
    current: 1,
    total: 1,
    etaText: null,
  } satisfies RunRecord;

  completeRuns([finished]);
  completeRuns([finished]);

  expect(seen).toEqual([[finished]]);
});

it("keeps a failed revise visible for the retry UI", () => {
  vi.useFakeTimers();
  useRunStore.setState({ runs: {} });
  completeRuns([
    {
      runId: "r9",
      kind: "revise",
      status: "failed",
      percent: 40,
      phase: "",
      current: 0,
      total: 1,
      etaText: null,
      error: "boom",
      meta: { versionId: 3, instruction: "tighten the summary" },
    },
  ]);

  vi.advanceTimersByTime(10_000);
  expect(useRunStore.getState().runs.r9).toBeDefined();
  vi.useRealTimers();
});

function page(items: unknown[]) {
  return { data: { data: items, pagination: { totalPages: 1 } }, error: undefined };
}

function payload(overrides: Record<string, unknown> = {}) {
  return {
    runId: "r1",
    kind: "tailor",
    state: "done",
    label: "Done",
    percent: 100,
    current: 1,
    total: 1,
    ...overrides,
  };
}

it("reconnects indefinitely with backoff instead of giving up after one try", async () => {
  vi.useFakeTimers();
  // The run must stay listed as running: an unlisted tracked run is now
  // resolved and untracked, which is a different behaviour under test.
  mocks.apiGet.mockResolvedValue(page([payload({ state: "running" })]));
  trackRun({ runId: "r1", kind: "tailor" });

  // Fail the transport five times; the old `reconnects < 1` cap gave up after one.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const onError = mocks.watchRun.mock.calls.at(-1)![3] as () => void;
    onError();
    await vi.advanceTimersByTimeAsync(60_000);
  }

  expect(mocks.watchRun.mock.calls.length).toBeGreaterThan(5);
  expect(isTracking("r1")).toBe(true);
  vi.useRealTimers();
});

it("finishes a tracked run the poller finds terminal", async () => {
  mocks.apiGet.mockResolvedValue(page([payload()]));
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));
  trackRun({ runId: "r1", kind: "tailor" });

  await pollRunsNow();

  expect(seen.flat().map((run) => run.runId)).toEqual(["r1"]);
  expect(isTracking("r1")).toBe(false);
});

it("announces a terminal run it never tracked", async () => {
  mocks.apiGet.mockResolvedValue(page([payload({ runId: "orphan" })]));
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));

  await pollRunsNow();

  expect(seen.flat().map((run) => run.runId)).toEqual(["orphan"]);
});

it("starts tracking an active run it discovers", async () => {
  mocks.apiGet.mockResolvedValue(
    page([payload({ runId: "live", state: "running", percent: 40 })]),
  );

  await pollRunsNow();

  expect(isTracking("live")).toBe(true);
});

it("treats a failed poll as no news about any run", async () => {
  mocks.apiGet.mockRejectedValue(new Error("offline"));
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));
  trackRun({ runId: "r1", kind: "tailor" });

  await pollRunsNow();

  expect(seen).toEqual([]);
  expect(isTracking("r1")).toBe(true);
});

it("reconciles every page of runs, not just the first", async () => {
  mocks.apiGet.mockImplementation((_path: string, opts: { params: { query: { page: number } } }) => {
    const p = opts.params.query.page;
    return Promise.resolve({
      data: {
        data: [payload({ runId: `r${p}`, state: "running", percent: p * 10 })],
        pagination: { totalPages: 2 },
      },
      error: undefined,
    });
  });

  await pollRunsNow();

  expect(isTracking("r1")).toBe(true);
  expect(isTracking("r2")).toBe(true);
  expect(useRunStore.getState().runs.r2?.percent).toBe(20);
});

it("retries the run list once after a transient failure", async () => {
  mocks.apiGet
    .mockRejectedValueOnce(new Error("503"))
    .mockResolvedValue(page([payload({ runId: "live", state: "running" })]));

  await pollRunsNow();

  expect(isTracking("live")).toBe(true);
});

it("does not apply a poll that lands after the poller was stopped", async () => {
  mocks.apiGet.mockImplementation(async () => {
    stopRunPoller();
    return page([payload({ runId: "late", state: "running" })]);
  });

  await pollRunsNow();

  expect(isTracking("late")).toBe(false);
});

it("does not re-announce a terminal run the server says was already announced", async () => {
  // A failed revision stays in /api/runs after ack because the retry UI needs
  // it. Announcing every terminal run in the payload re-toasted the same
  // failure on every page load until the 24h sweep.
  mocks.apiGet.mockResolvedValue(
    page([
      payload({
        runId: "old-failure",
        kind: "revise",
        state: "error",
        announcedAt: "2026-08-23T00:00:00Z",
        meta: { versionId: 5, instruction: "shorter" },
      }),
    ]),
  );
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));

  await pollRunsNow();

  expect(seen).toEqual([]);
  // Still on screen for the retry UI, just not announced again.
  expect(useRunStore.getState().runs["old-failure"]).toBeDefined();
});

it("resolves a tracked run the listing no longer mentions", async () => {
  mocks.apiGet.mockImplementation((path: string) =>
    path === "/api/runs"
      ? Promise.resolve(page([]))
      : Promise.resolve({ data: payload({ runId: "gone" }), error: undefined }),
  );
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));
  trackRun({ runId: "gone", kind: "tailor" });

  await pollRunsNow();

  expect(seen.flat().map((run) => run.runId)).toEqual(["gone"]);
  expect(isTracking("gone")).toBe(false);
});

it("stops tracking a run that was swept, so its bar cannot freeze", async () => {
  mocks.apiGet.mockImplementation((path: string) =>
    path === "/api/runs"
      ? Promise.resolve(page([]))
      : Promise.reject(new Error("404")),
  );
  trackRun({ runId: "swept", kind: "tailor" });

  await pollRunsNow();

  expect(isTracking("swept")).toBe(false);
  expect(useRunStore.getState().runs.swept).toBeUndefined();
});

it("coalesces concurrent reconciliations into one request", async () => {
  mocks.apiGet.mockResolvedValue(page([]));

  await Promise.all([pollRunsNow(), pollRunsNow(), pollRunsNow()]);

  const listCalls = mocks.apiGet.mock.calls.filter(
    (call: unknown[]) => call[0] === "/api/runs",
  );
  expect(listCalls).toHaveLength(1);
});

it("keeps a completion found by a poll that raced the idle stop", async () => {
  // The idle stop used to bump the generation, so whichever concurrent poll
  // finished first invalidated the others -- discarding a completion they had
  // already fetched.
  mocks.apiGet.mockResolvedValue(page([payload({ runId: "racer" })]));
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));

  await pollRunsNow();
  resetRunTrackerForTests();
  addTerminalListener((runs) => seen.push(runs));
  await pollRunsNow();

  expect(seen.flat().map((run) => run.runId)).toEqual(["racer", "racer"]);
});

it("resets the reconnect delay when a frame arrives", async () => {
  vi.useFakeTimers();
  mocks.apiGet.mockResolvedValue(page([payload({ state: "running" })]));
  trackRun({ runId: "r1", kind: "tailor" });

  const failThenCount = async () => {
    const before = mocks.watchRun.mock.calls.length;
    (mocks.watchRun.mock.calls.at(-1)![3] as () => void)();
    await vi.advanceTimersByTimeAsync(1100);
    return mocks.watchRun.mock.calls.length > before;
  };

  // First failure reconnects within the 1s base delay (plus jitter headroom).
  expect(await failThenCount()).toBe(true);
  // Second failure has doubled, so 1.1s is no longer enough...
  expect(await failThenCount()).toBe(false);
  await vi.advanceTimersByTimeAsync(60_000);

  // ...until a frame arrives and resets it.
  (mocks.watchRun.mock.calls.at(-1)![4] as () => void)();
  expect(await failThenCount()).toBe(true);
  vi.useRealTimers();
});
