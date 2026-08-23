import { beforeEach, expect, it, vi } from "vitest";

import type { RunRecord } from "./store";

const mocks = vi.hoisted(() => ({ apiGet: vi.fn(), watchRun: vi.fn() }));
vi.mock("@/lib/api/client", () => ({
  api: { GET: mocks.apiGet },
  unwrap: async (request: Promise<unknown>) => request,
}));
vi.mock("./sse", () => ({
  stateToStatus: (state: string) => (state === "done" ? "succeeded" : "running"),
  watchRun: mocks.watchRun,
}));

import {
  addTerminalListener,
  completeRuns,
  isTracking,
  resetRunTrackerForTests,
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
