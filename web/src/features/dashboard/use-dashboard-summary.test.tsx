import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { SUMMARY } from "./fixtures";
import { useDashboardSummary } from "./use-dashboard-summary";

describe("useDashboardSummary", () => {
  it("loads the summary projection", async () => {
    server.use(
      http.get("/api/dashboard/summary", () => HttpResponse.json(SUMMARY)),
    );

    const { result } = renderHook(() => useDashboardSummary(), {
      wrapper: withQueryClient,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.queues.approve).toBe(4);
    expect(result.current.data?.applied).toBe(5);
  });
});
