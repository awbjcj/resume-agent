import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDismissAllErrors, useErrorRecords } from "./use-errors";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  unwrap: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  api: { GET: mocks.get, POST: mocks.post },
  unwrap: mocks.unwrap,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function wrap() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidate };
}

describe("error hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.unwrap.mockResolvedValue({ errors: [] });
  });

  it("lists open errors by default, requesting the backend's max page size", async () => {
    // AttentionCard has no pagination UI of its own -- it shows "everything
    // open" behind a local Show all toggle, so it must ask for as many rows
    // as the server will return in one call, not the 50-row default page.
    const { wrapper } = wrap();
    const { result } = renderHook(() => useErrorRecords(), { wrapper });

    await act(async () => {
      await result.current.refetch();
    });

    expect(mocks.get).toHaveBeenCalledWith("/api/errors", {
      params: { query: { status: "open", pageSize: 200 } },
    });
  });

  it("dismisses all errors and invalidates errors and dashboard", async () => {
    const { wrapper, invalidate } = wrap();
    const { result } = renderHook(() => useDismissAllErrors(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(mocks.post).toHaveBeenCalledWith("/api/errors/dismiss-all", {});
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["error-records"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard-summary"] });
  });
});
