import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";
import { useSuggestionRunRegistry } from "./suggestion-run-registry";
import { useSuggestionRuns } from "./use-suggestion-runs";

const watchRun = vi.fn();
vi.mock("@/lib/runs/sse", () => ({
  watchRun: (...args: unknown[]) => watchRun(...args),
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

beforeEach(() => {
  watchRun.mockReset();
  useRunStore.setState({ runs: {} });
  useSuggestionRunRegistry.setState({ entries: {}, launchError: null });
});

it("registers every accepted target and watches its run", async () => {
  server.use(
    http.post("/api/suggestion-runs", () =>
      HttpResponse.json({
        results: [
          {
            outcome: "accepted",
            kind: "skill",
            key: "python",
            runId: "r1",
          },
        ],
      }),
    ),
  );
  const { result } = renderHook(() => useSuggestionRuns(() => undefined), { wrapper });

  await act(() =>
    result.current.generateAll([{ kind: "skill", key: "python", label: "Python" }]),
  );

  expect(useRunStore.getState().runs.r1.status).toBe("queued");
  expect(useSuggestionRunRegistry.getState().entries).toEqual(
    expect.objectContaining({
      '["skill","python"]': expect.objectContaining({ runId: "r1" }),
    }),
  );
  expect(watchRun).toHaveBeenCalledWith("r1", "suggestion", expect.any(Function));
});
