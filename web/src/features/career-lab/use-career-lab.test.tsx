import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCareerLabRecoveredRun,
  useRenameCareerLabSession,
  useCareerLabSessions,
  useSendCareerLabMessage,
  useStartCareerLab,
} from "./use-career-lab";
import { useRunStore } from "@/lib/runs/store";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  unwrap: vi.fn(),
  trackRun: vi.fn(),
  upsert: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  api: { GET: mocks.get, POST: mocks.post, PATCH: mocks.patch },
  unwrap: mocks.unwrap,
}));
vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function wrap() {
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidate: vi.spyOn(queryClient, "invalidateQueries") };
}

beforeEach(() => {
  vi.clearAllMocks();
  useRunStore.setState({ runs: {} });
  mocks.unwrap.mockResolvedValue({
    runId: "career-run",
    kind: "career-lab-turn",
    state: "pending",
    label: "",
    percent: 0,
    current: 0,
    total: 0,
    meta: { sessionId: "s1" },
  });
});

describe("Career Lab hooks", () => {
  it("starts a typed draft turn and tracks the returned run", async () => {
    const { wrapper } = wrap();
    const { result } = renderHook(() => useStartCareerLab(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        message: "Compare the offers",
        goal: "Choose a negotiation strategy",
        skill: "offer-comparison-analyzer",
        context: { jobId: 7, resumeVersionId: 3, offerApplicationIds: [12] },
      });
    });

    expect(mocks.post).toHaveBeenCalledWith("/api/career-lab/sessions", {
      body: {
        message: "Compare the offers",
        goal: "Choose a negotiation strategy",
        skill: "offer-comparison-analyzer",
        context: { jobId: 7, resumeVersionId: 3, offerApplicationIds: [12] },
      },
    });
    expect(mocks.trackRun).toHaveBeenCalledWith(
      { runId: "career-run", kind: "career-lab-turn" },
      expect.any(Function),
    );
  });

  it("sends a follow-up with its session context", async () => {
    const { wrapper } = wrap();
    const { result } = renderHook(() => useSendCareerLabMessage(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        sessionId: "s1",
        message: "Make it concise",
        skill: "salary-negotiation-prep",
        context: { offerApplicationIds: [] },
      });
    });

    expect(mocks.post).toHaveBeenCalledWith(
      "/api/career-lab/sessions/{session_id}/messages",
      {
        params: { path: { session_id: "s1" } },
        body: {
          message: "Make it concise",
          skill: "salary-negotiation-prep",
          context: { offerApplicationIds: [] },
        },
      },
    );
  });

  it("passes the archived-session filter to the generated API query", async () => {
    mocks.unwrap.mockResolvedValueOnce({ sessions: [], pagination: { page: 1, pageSize: 20, totalItems: 0, totalPages: 0 } });
    const { wrapper } = wrap();
    const { result } = renderHook(() => useCareerLabSessions(true), { wrapper });

    await act(async () => {
      await result.current.refetch();
    });

    expect(mocks.get).toHaveBeenCalledWith("/api/career-lab/sessions", {
      params: { query: { includeArchived: true, page: 1, pageSize: 20 } },
    });
  });

  it("renames a session and refreshes session queries", async () => {
    mocks.unwrap.mockResolvedValueOnce({ sessionId: "s1", title: "Equity trade-offs" });
    const { wrapper, invalidate } = wrap();
    const { result } = renderHook(() => useRenameCareerLabSession(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ sessionId: "s1", title: "Equity trade-offs" });
    });

    expect(mocks.patch).toHaveBeenCalledWith("/api/career-lab/sessions/{session_id}", {
      params: { path: { session_id: "s1" } },
      body: { title: "Equity trade-offs" },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["career-lab-sessions"] });
  });

  it("rehydrates an active start run before a session id exists", () => {
    useRunStore.getState().upsert({
      runId: "start-run",
      kind: "career-lab-turn",
      status: "running",
      percent: 20,
      phase: "Drafting",
      current: 1,
      total: 2,
      etaText: null,
      meta: null,
    });
    const { result } = renderHook(() => useCareerLabRecoveredRun(null));
    expect(result.current?.runId).toBe("start-run");
  });
});
