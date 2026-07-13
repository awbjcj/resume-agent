import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { useDeleteJob } from "./use-delete-job";

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("useDeleteJob", () => {
  it("surfaces a guarded delete as an error", async () => {
    server.use(http.delete("/api/jobs/9", () => HttpResponse.json(
      { error: { code: "HAS_PROGRESS", message: "Job has progress" } },
      { status: 409 },
    )));
    const { result } = renderHook(() => useDeleteJob(), { wrapper });
    result.current.mutate(9);
    await waitFor(() => expect(result.current.error?.message).toBe("Job has progress"));
  });
});
