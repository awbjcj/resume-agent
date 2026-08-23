import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";

import { rememberInvalidation, resetInvalidationForTests } from "@/lib/runs/invalidation";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { completeRuns, resetRunTrackerForTests } from "@/lib/runs/tracker";
import { server } from "@/test/server";

const mocks = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
    info: mocks.toastInfo,
  },
}));

import { useRunCompletionEffects } from "./use-run-completion-effects";

function finished(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "Done",
    current: 1,
    total: 1,
    etaText: null,
    result: { jobs: [{ jobId: 1, versionCount: 3 }] },
    ...overrides,
  };
}

function mount(qc: QueryClient) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(() => useRunCompletionEffects(), { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  resetRunTrackerForTests();
  resetInvalidationForTests();
  useRunStore.setState({ runs: {} });
});

it("announces, acknowledges, and invalidates a completion", async () => {
  const acked: string[][] = [];
  server.use(
    http.post("/api/runs/ack", async ({ request }) => {
      const body = (await request.json()) as { runIds: string[] };
      acked.push(body.runIds);
      return HttpResponse.json({ acknowledged: body.runIds.length });
    }),
  );
  const qc = new QueryClient();
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  mount(qc);

  act(() => completeRuns([finished()]));

  expect(mocks.toastSuccess).toHaveBeenCalledWith(
    expect.stringMatching(/3 resume versions.*render PDF/i),
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job"] });
  await waitFor(() => expect(acked).toEqual([["r1"]]));
});

it("uses the keys the launch site registered for that run", () => {
  const qc = new QueryClient();
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  mount(qc);
  rememberInvalidation("r1", ["match-gap"]);

  act(() => completeRuns([finished()]));

  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["match-gap"] });
  expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["job"] });
});

it("collapses a reconnect batch into one summary and acks every run", async () => {
  const acked: string[][] = [];
  server.use(
    http.post("/api/runs/ack", async ({ request }) => {
      const body = (await request.json()) as { runIds: string[] };
      acked.push(body.runIds);
      return HttpResponse.json({ acknowledged: body.runIds.length });
    }),
  );
  mount(new QueryClient());

  act(() =>
    completeRuns([
      finished({ runId: "a" }),
      finished({ runId: "b" }),
      finished({ runId: "c" }),
      finished({ runId: "d" }),
    ]),
  );

  expect(mocks.toastSuccess).toHaveBeenCalledOnce();
  expect(mocks.toastSuccess.mock.calls[0][0]).toContain("4 runs finished");
  await waitFor(() => expect(acked).toEqual([["a", "b", "c", "d"]]));
});

it("stops reacting once unmounted", () => {
  const qc = new QueryClient();
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  const { unmount } = mount(qc);

  unmount();
  act(() => completeRuns([finished()]));

  expect(mocks.toastSuccess).not.toHaveBeenCalled();
  expect(invalidate).not.toHaveBeenCalled();
});
