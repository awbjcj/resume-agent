import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  active: null as { status: string } | null,
  launch: vi.fn(),
}));

vi.mock("@/features/runs/use-active-run", () => ({
  useActiveRun: () => mocks.active,
}));

vi.mock("@/features/runs/use-launch-run", () => ({
  launchers: { githubSync: vi.fn() },
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

import { useSyncGithub } from "./use-sources";
import { useUploadSources } from "./use-sources";
import { server } from "@/test/server";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("useSyncGithub", () => {
  beforeEach(() => {
    mocks.active = null;
    mocks.launch.mockReset();
  });

  it("stays pending while the tracked run launch request is in flight", async () => {
    let finish!: (value: boolean) => void;
    mocks.launch.mockReturnValue(new Promise<boolean>((resolve) => { finish = resolve; }));
    const { result } = renderHook(() => useSyncGithub());

    act(() => result.current.mutate());
    expect(result.current.isPending).toBe(true);

    act(() => finish(true));
    await waitFor(() => expect(result.current.isPending).toBe(false));
  });

  it.each(["queued", "running", "cancelling"])(
    "is pending for a %s run",
    (status) => {
      mocks.active = { status };
      const { result } = renderHook(() => useSyncGithub());
      expect(result.current.isPending).toBe(true);
    },
  );
});

describe("useUploadSources", () => {
  it("uploads a batch sequentially and isolates failures", async () => {
    let calls = 0;
    server.use(
      http.post("/api/profile/sources", () => {
        calls += 1;
        if (calls === 2) {
          return HttpResponse.json(
            { error: { code: "BAD_FILE", message: "unsupported" } },
            { status: 400 },
          );
        }
        return HttpResponse.json({ id: `doc-${calls}` });
      }),
    );
    const { result } = renderHook(() => useUploadSources(), { wrapper });
    const files = [
      new File(["a"], "a.md", { type: "text/markdown" }),
      new File(["b"], "b.md", { type: "text/markdown" }),
      new File(["c"], "c.md", { type: "text/markdown" }),
    ];

    const summary = await result.current.uploadAll(files, "literal", null);

    expect(summary.ok).toBe(2);
    expect(summary.failed).toEqual([["b.md", "unsupported"]]);
    expect(calls).toBe(3);
  });
});
