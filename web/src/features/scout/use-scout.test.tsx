import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApproveScoutProposal, useScoutSession, useStartScoutSession } from "./use-scout";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), track: vi.fn(), unwrap: vi.fn(), upsert: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api: { GET: mocks.get, POST: mocks.post, DELETE: vi.fn() }, unwrap: mocks.unwrap }));
vi.mock("@/lib/runs/store", () => ({ useRunStore: { getState: () => ({ upsert: mocks.upsert }) } }));
vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.track }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

describe("Scout hooks", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.unwrap.mockResolvedValue({ runId: "run-1", kind: "scout-start", state: "pending", label: "", percent: 0, current: 0, total: 0 }); });

  it("does not load detail without a session id", () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useScoutSession(null), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("starts with the user's first message and tracks the run", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useStartScoutSession(), { wrapper });
    await act(async () => { await result.current.mutateAsync({ message: "Find climate roles" }); });
    expect(mocks.post).toHaveBeenCalledWith("/api/scout/sessions", { body: { message: "Find climate roles" } });
    expect(mocks.upsert).toHaveBeenCalledWith(expect.objectContaining({ runId: "run-1", kind: "scout-start" }));
    expect(mocks.track).toHaveBeenCalled();
  });

  it("refreshes Scout, source, and search data after approval", async () => {
    mocks.unwrap.mockResolvedValue({});
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useApproveScoutProposal(), { wrapper });
    await act(async () => { await result.current.mutateAsync({ sessionId: "s1", proposalId: "p1" }); });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["scout-session"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["sources"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["config", "/api/config/search"] });
  });
});
