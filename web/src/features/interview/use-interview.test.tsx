import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useArchiveInterviewSession,
  useInterviewAudioAvailability,
  useInterviewSessions,
  useSendInterviewAnswer,
  useStartInterview,
} from "./use-interview";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
  delete: vi.fn(),
  trackRun: vi.fn(),
  unwrap: vi.fn(),
  upsert: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  api: { GET: mocks.get, POST: mocks.post, DELETE: mocks.delete },
  unwrap: mocks.unwrap,
}));

vi.mock("@/lib/runs/store", () => ({
  useRunStore: { getState: () => ({ upsert: mocks.upsert }) },
}));

vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function wrap() {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidate };
}

describe("interview hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.unwrap.mockResolvedValue({
      runId: "run-1",
      kind: "mock-interview-open",
      state: "pending",
      label: "",
      percent: 0,
      current: 0,
      total: 0,
    });
  });

  it("useStartInterview POSTs the camelCase body and invalidates on completion", async () => {
    const { wrapper, invalidate } = wrap();
    const { result } = renderHook(() => useStartInterview(), { wrapper });
    const style = {
      stage: "technical",
      demeanor: "neutral",
      difficulty: "standard",
      questionCount: 4,
      extra: "",
      responseMode: "text" as const,
    };

    await act(async () => {
      await result.current.mutateAsync({
        jobId: 7,
        resumeVersionId: 3,
        style,
      });
    });

    expect(mocks.post).toHaveBeenCalledWith("/api/interview/sessions", {
      body: { jobId: 7, resumeVersionId: 3, style },
    });

    const onDone = mocks.trackRun.mock.calls[0][1];
    await act(async () => {
      await onDone({ status: "succeeded", result: { sessionId: "s1" } });
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["interview-sessions"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["interview-session"] });
  });

  it("useSendInterviewAnswer hits the messages endpoint", async () => {
    const { wrapper } = wrap();
    const { result } = renderHook(() => useSendInterviewAnswer(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ sessionId: "s1", message: "My answer" });
    });

    expect(mocks.post).toHaveBeenCalledWith(
      "/api/interview/sessions/{session_id}/messages",
      { params: { path: { session_id: "s1" } }, body: { message: "My answer" } },
    );
  });

  it("archives a session and invalidates session queries", async () => {
    const { wrapper, invalidate } = wrap();
    const { result } = renderHook(() => useArchiveInterviewSession(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ sessionId: "s1" });
    });

    expect(mocks.post).toHaveBeenCalledWith(
      "/api/interview/sessions/{session_id}/archive",
      { params: { path: { session_id: "s1" } } },
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["interview-sessions"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard-summary"] });
  });

  it("passes includeArchived to the sessions list", async () => {
    mocks.unwrap.mockResolvedValueOnce({ sessions: [] });
    const { wrapper } = wrap();
    const { result } = renderHook(() => useInterviewSessions(undefined, true), {
      wrapper,
    });

    await act(async () => {
      await result.current.refetch();
    });

    expect(mocks.get).toHaveBeenCalledWith("/api/interview/sessions", {
      params: { query: { includeArchived: true } },
    });
  });

  it("checks whether interviewer audio is available", async () => {
    mocks.unwrap.mockResolvedValueOnce({ available: true });
    const { wrapper } = wrap();
    const { result } = renderHook(() => useInterviewAudioAvailability(), { wrapper });

    await act(async () => {
      await result.current.refetch();
    });

    expect(mocks.get).toHaveBeenCalledWith("/api/interview/audio/availability");
  });
});
