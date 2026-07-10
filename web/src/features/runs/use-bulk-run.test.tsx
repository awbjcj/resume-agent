import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useBulkRun } from "./use-bulk-run";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useBulkRun", () => {
  it("exposes selected-job launchers", () => {
    const { result } = renderHook(() => useBulkRun(), { wrapper });
    expect(typeof result.current.tailorSelected).toBe("function");
    expect(typeof result.current.coverLettersSelected).toBe("function");
  });
});
