import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { useApplicationEvents } from "./use-application-events";

describe("useApplicationEvents", () => {
  it("loads the job timeline from the generated API contract", async () => {
    server.use(
      http.get("/api/jobs/42/events", () =>
        HttpResponse.json([
          {
            id: 7,
            applicationId: 3,
            kind: "technical_round",
            sequence: 1,
            occurredAt: "2026-03-09T19:00:00Z",
            allDay: false,
            result: "pending",
            source: "manual",
            createdAt: "2026-03-01T00:00:00Z",
            updatedAt: "2026-03-01T00:00:00Z",
            totalComp: null,
          },
        ]),
      ),
    );
    const { result } = renderHook(() => useApplicationEvents(42), {
      wrapper: withQueryClient,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].id).toBe(7);
  });
});
