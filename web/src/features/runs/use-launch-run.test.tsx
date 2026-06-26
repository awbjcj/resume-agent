import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunRecord } from "@/lib/runs/store";

const mocks = vi.hoisted(() => ({
  watchRun: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}));

vi.mock("@/lib/runs/sse", () => ({ watchRun: mocks.watchRun }));
vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError, info: mocks.toastInfo },
}));

import { useLaunchRun } from "./use-launch-run";

describe("useLaunchRun", () => {
  beforeEach(() => vi.clearAllMocks());

  it("refreshes job details and announces generated resume versions on completion", async () => {
    const qc = new QueryClient();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    let onDone: ((run: RunRecord) => void) | undefined;
    mocks.watchRun.mockImplementation((_id, _kind, callback) => {
      onDone = callback;
      return vi.fn();
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLaunchRun(), { wrapper });

    await act(() =>
      result.current.launch("tailor", async () => ({ runId: "r1", kind: "tailor" })),
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
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      expect.stringMatching(/3 resume versions.*render PDF/i),
    );
  });
});
