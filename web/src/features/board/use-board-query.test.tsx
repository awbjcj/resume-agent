import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { emptyFilterState } from "@/lib/filters/types";
import { server } from "@/test/server";

import { type TriageItem, useBoardQuery } from "./use-board-query";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useBoardQuery", () => {
  it("exposes rows, facets, and total from the envelope", async () => {
    server.use(
      http.get("/api/triage", () =>
        HttpResponse.json({
          data: [{ jobId: 1, company: "Acme", source: "adzuna", status: "rejected" }],
          pagination: { page: 1, pageSize: 50, totalItems: 1, totalPages: 1 },
          facets: { source: { adzuna: 1 } },
          total: 1,
        }),
      ),
    );
    const { result } = renderHook(
      () => useBoardQuery<TriageItem>("triage", emptyFilterState(), { archived: false }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.rows[0].jobId).toBe(1);
    expect(result.current.facets.source.adzuna).toBe(1);
    expect(result.current.total).toBe(1);
  });
});
