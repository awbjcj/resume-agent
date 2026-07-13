import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { useArchiveJob } from "./use-archive-job";

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("useArchiveJob", () => {
  it("archives by default", async () => {
    let body: unknown;
    server.use(http.patch("/api/jobs/7", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({});
    }));
    const { result } = renderHook(() => useArchiveJob(), { wrapper });
    result.current.mutate({ jobId: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(body).toEqual({ archived: true });
  });
});
