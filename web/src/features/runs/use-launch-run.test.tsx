import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_INVALIDATE,
  invalidationKeys,
  resetInvalidationForTests,
} from "@/lib/runs/invalidation";
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
    resetInvalidationForTests();
    useRunStore.setState({ runs: {} });
  });

  it("registers the run's invalidation keys and tracks it without owning completion effects", async () => {
    // Completion effects used to live in this closure, which is precisely why a
    // run discovered on page load refreshed nothing: the closure was gone. The
    // launch site now only records which queries THIS run invalidates.
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch(
        "tailor",
        async () => ({ runId: "r1", kind: "tailor" }),
        ["job"],
      ),
    );

    expect(mocks.trackRun).toHaveBeenCalledWith({ runId: "r1", kind: "tailor" });
    expect(invalidationKeys("r1", "tailor")).toEqual(["job"]);
    expect(mocks.toastSuccess).not.toHaveBeenCalled();
  });

  it("falls back to the default keys when the caller names none", async () => {
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch("tailor", async () => ({ runId: "r2", kind: "tailor" })),
    );

    expect(invalidationKeys("r2", "tailor")).toEqual([...DEFAULT_INVALIDATE]);
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

  it("uses authoritative run metadata returned by the backend", async () => {
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch("coverLetter", async () => ({
        runId: "bulk-cl",
        kind: "coverLetter",
        meta: { jobIds: [3, 8] },
      })),
    );

    expect(useRunStore.getState().runs["bulk-cl"].meta).toEqual({ jobIds: [3, 8] });
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
