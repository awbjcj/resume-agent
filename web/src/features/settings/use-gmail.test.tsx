import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useGmailConnectOutcome } from "./use-gmail";

const toast = { success: vi.fn(), error: vi.fn() };
vi.mock("sonner", () => ({ toast: { success: (m: string) => toast.success(m), error: (m: string) => toast.error(m) } }));

function makeWrapper(entry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[entry]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("useGmailConnectOutcome", () => {
  beforeEach(() => {
    toast.success.mockClear();
    toast.error.mockClear();
  });

  it("shows an error toast and strips the param on a failure outcome", async () => {
    const { result } = renderHook(
      () => {
        useGmailConnectOutcome();
        return useLocation();
      },
      { wrapper: makeWrapper("/settings/keys?gmail=error&keep=1") },
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(toast.success).not.toHaveBeenCalled();
    // the gmail param is cleared so a refresh won't re-toast; unrelated params survive
    expect(result.current.search).not.toContain("gmail=");
    expect(result.current.search).toContain("keep=1");
  });

  it("shows a success toast on the connected outcome", async () => {
    renderHook(
      () => {
        useGmailConnectOutcome();
        return useLocation();
      },
      { wrapper: makeWrapper("/settings/keys?gmail=connected") },
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does nothing when there is no gmail param", async () => {
    renderHook(
      () => {
        useGmailConnectOutcome();
        return useLocation();
      },
      { wrapper: makeWrapper("/settings/keys") },
    );
    await new Promise((r) => setTimeout(r, 20));
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
