import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useEndCoachSession } from "./use-coach";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  trackRun: vi.fn(),
  unwrap: vi.fn(),
  upsert: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  api: { POST: mocks.post },
  unwrap: mocks.unwrap,
}));

vi.mock("@/lib/runs/store", () => ({
  useRunStore: { getState: () => ({ upsert: mocks.upsert }) },
}));

vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

describe("useEndCoachSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.unwrap.mockResolvedValue({
      runId: "end-run",
      kind: "profile-coach-end",
      state: "pending",
      label: "",
      percent: 0,
      current: 0,
      total: 0,
    });
  });

  it("refetches the coach session after the impact build completes", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useEndCoachSession(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ sessionId: "session-1", build: true });
    });
    const endDone = mocks.trackRun.mock.calls[0][1];
    await act(async () => {
      await endDone({
        status: "succeeded",
        result: { buildRunId: "build-run" },
      });
    });

    invalidate.mockClear();
    const buildDone = mocks.trackRun.mock.calls[1][1];
    await act(async () => {
      await buildDone({ status: "succeeded", result: null });
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["coach-session", "session-1"],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coach-sessions"] });
  });
});
