import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { useShortlist } from "./use-shortlist";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useShortlist", () => {
  it("returns the fetched rows", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [{ jobId: 1, company: "Acme", title: "Eng", skills: [] }],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
        }),
      ),
    );
    const { result } = renderHook(() => useShortlist(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.[0].jobId).toBe(1);
  });
});
