import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";

const mocks = vi.hoisted(() => ({ trackRun: vi.fn() }));
vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));

import { useRehydrateRuns } from "./use-rehydrate-runs";

beforeEach(() => {
  mocks.trackRun.mockReset();
  useRunStore.setState({ runs: {} });
});

it("fetches every active page, refreshes the store, and tracks each run", async () => {
  server.use(
    http.get("/api/runs", ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get("page") ?? 1);
      const item = {
        runId: `r${page}`,
        kind: "pull",
        state: "running",
        label: `Page ${page}`,
        percent: page * 10,
        current: page,
        total: 10,
        etaText: null,
        result: null,
        error: null,
        meta: page === 1 ? { versionId: 5, jobId: 3, instruction: "shorter" } : null,
      };
      return HttpResponse.json({
        data: [item],
        pagination: { page, pageSize: 200, totalItems: 2, totalPages: 2 },
      });
    }),
  );
  useRunStore.getState().upsert({
    runId: "r1",
    kind: "pull",
    status: "queued",
    percent: 0,
    phase: "stale",
    current: 0,
    total: 0,
    etaText: null,
  });

  renderHook(() => useRehydrateRuns());

  await waitFor(() => expect(mocks.trackRun).toHaveBeenCalledTimes(2));
  expect(useRunStore.getState().runs.r1.phase).toBe("Page 1");
  expect(useRunStore.getState().runs.r1.meta).toEqual({
    versionId: 5,
    jobId: 3,
    instruction: "shorter",
  });
  expect(useRunStore.getState().runs.r2.percent).toBe(20);
  expect(mocks.trackRun).toHaveBeenCalledWith({ runId: "r1", kind: "pull" });
  expect(mocks.trackRun).toHaveBeenCalledWith({ runId: "r2", kind: "pull" });
});

it("ignores a late response after unmount", async () => {
  let resolve: (() => void) | undefined;
  server.use(
    http.get("/api/runs", async () => {
      await new Promise<void>((done) => {
        resolve = done;
      });
      return HttpResponse.json({
        data: [],
        pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
      });
    }),
  );

  const { unmount } = renderHook(() => useRehydrateRuns());
  unmount();
  resolve?.();
  await Promise.resolve();

  expect(mocks.trackRun).not.toHaveBeenCalled();
});

it("retries the active-run list once after a transient failure", async () => {
  let attempts = 0;
  server.use(
    http.get("/api/runs", () => {
      attempts += 1;
      if (attempts === 1) return HttpResponse.json({}, { status: 503 });
      return HttpResponse.json({
        data: [],
        pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
      });
    }),
  );

  renderHook(() => useRehydrateRuns());

  await waitFor(() => expect(attempts).toBe(2));
});

it("rehydrates a failed revision without tracking a terminal run", async () => {
  server.use(
    http.get("/api/runs", () =>
      HttpResponse.json({
        data: [{
          runId: "failed-revision",
          kind: "revise",
          state: "error",
          label: "Failed",
          percent: 0,
          current: 0,
          total: 0,
          etaText: null,
          result: null,
          error: "provider failed",
          meta: { versionId: 5, jobId: 3, instruction: "shorter" },
        }],
        pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
      }),
    ),
  );

  renderHook(() => useRehydrateRuns());

  await waitFor(() =>
    expect(useRunStore.getState().runs["failed-revision"]?.status).toBe("failed"),
  );
  expect(mocks.trackRun).not.toHaveBeenCalled();
});
