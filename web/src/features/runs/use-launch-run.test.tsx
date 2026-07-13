import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";

const mocks = vi.hoisted(() => ({
  trackRun: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}));

vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));
vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError, info: mocks.toastInfo },
}));

import { useLaunchRun } from "./use-launch-run";

describe("useLaunchRun", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("refreshes job details and announces generated resume versions on completion", async () => {
    const qc = new QueryClient();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    let onDone: ((run: RunRecord) => void) | undefined;
    mocks.trackRun.mockImplementation((_seed, callback) => {
      onDone = callback;
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch("tailor", async () => ({ runId: "r1", kind: "tailor" })),
    );
    expect(mocks.trackRun).toHaveBeenCalledWith(
      { runId: "r1", kind: "tailor" },
      expect.any(Function),
    );
    expect(onDone).toBeDefined();

    act(() => {
      onDone!({
        runId: "r1",
        kind: "tailor",
        status: "succeeded",
        percent: 100,
        phase: "Tailoring",
        current: 1,
        total: 1,
        etaText: null,
        result: { jobs: [{ jobId: 1, versionCount: 3 }] },
      });
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job"] });
    await waitFor(() =>
      expect(mocks.toastSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/3 resume versions.*render PDF/i),
      ),
    );
  });

  it("keeps durable artifact metadata on the optimistic run", async () => {
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch(
        "revise",
        async () => ({ runId: "r2", kind: "revise" }),
        ["job"],
        { versionId: 5, jobId: 3, instruction: "shorter", reReview: true },
      ),
    );

    expect(useRunStore.getState().runs.r2.meta).toEqual({
      versionId: 5,
      jobId: 3,
      instruction: "shorter",
      reReview: true,
    });
  });

  it("removes a superseded revision failure when its retry launches", async () => {
    useRunStore.getState().upsert({
      runId: "failed-r1",
      kind: "revise",
      status: "failed",
      percent: 0,
      phase: "Failed",
      current: 0,
      total: 0,
      etaText: null,
      error: "provider failed",
      meta: { versionId: 5, jobId: 3, instruction: "shorter" },
    });
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch(
        "revise",
        async () => ({ runId: "retry-r2", kind: "revise" }),
        ["job"],
        { versionId: 5, jobId: 3, instruction: "shorter" },
      ),
    );

    expect(useRunStore.getState().runs["failed-r1"]).toBeUndefined();
    expect(useRunStore.getState().runs["retry-r2"]?.status).toBe("running");
  });
});
