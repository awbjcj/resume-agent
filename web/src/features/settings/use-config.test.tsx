import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { useConfig, useSaveConfig } from "./use-config";

describe("useConfig", () => {
  it("fetches the config document", async () => {
    server.use(
      http.get("/api/config/prune", () =>
        HttpResponse.json({
          fitThreshold: 40,
          staleDays: 60,
          retentionDays: 30,
          enableRejected: true,
          enableLowFit: true,
          enableStale: true,
        }),
      ),
    );

    const { result } = renderHook(() => useConfig("/api/config/prune"), {
      wrapper: withQueryClient,
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.fitThreshold).toBe(40);
  });

  it("save mutation PUTs and resolves with the echoed doc", async () => {
    server.use(
      http.put("/api/config/prune", async ({ request }) => HttpResponse.json(await request.json())),
    );

    const { result } = renderHook(() => useSaveConfig("/api/config/prune"), {
      wrapper: withQueryClient,
    });
    const saved = await result.current.mutateAsync({
      fitThreshold: 55,
      staleDays: 60,
      retentionDays: 30,
      enableRejected: false,
      enableLowFit: true,
      enableStale: true,
    });
    expect(saved.fitThreshold).toBe(55);
  });
});
