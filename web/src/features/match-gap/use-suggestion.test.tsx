import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";

const mocks = vi.hoisted(() => ({
  watchRun: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}));

vi.mock("@/lib/runs/sse", () => ({ watchRun: mocks.watchRun }));
vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
    info: mocks.toastInfo,
  },
}));

import { useGenerateSuggestion, useSuggestion } from "./use-suggestion";

describe("suggestion hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("refetches the exact cached suggestion after generation completes", async () => {
    let gets = 0;
    let onDone: ((run: RunRecord) => void) | undefined;
    server.use(
      http.get("/api/suggestions", () => {
        gets += 1;
        return HttpResponse.json({
          stale: false,
          suggestion: gets === 1 ? null : { kind: "skill", key: "Kubernetes" },
        });
      }),
      http.post("/api/suggestions/generate", () =>
        HttpResponse.json({ runId: "run-1", kind: "suggestion" }),
      ),
    );
    mocks.watchRun.mockImplementation((_id, _kind, callback) => {
      onDone = callback;
      return vi.fn();
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () => ({
        suggestion: useSuggestion("skill", "Kubernetes", true),
        generation: useGenerateSuggestion(),
      }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.suggestion.isSuccess).toBe(true));

    await act(() => result.current.generation.generate("skill", "Kubernetes"));
    act(() => {
      onDone?.({
        runId: "run-1",
        kind: "suggestion",
        status: "succeeded",
        percent: 100,
        phase: "Researching",
        current: 1,
        total: 1,
        etaText: null,
        result: { kind: "skill", key: "Kubernetes" },
      });
    });

    await waitFor(() =>
      expect(result.current.suggestion.data?.suggestion?.key).toBe("Kubernetes"),
    );
    expect(gets).toBe(2);
  });
});
