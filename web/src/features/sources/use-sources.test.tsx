import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { useSources } from "./use-sources";

describe("useSources", () => {
  it("loads the source list", async () => {
    server.use(http.get("/api/sources", () => HttpResponse.json([])));

    const { result } = renderHook(() => useSources(), { wrapper: withQueryClient });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(Array.isArray(result.current.data)).toBe(true);
  });
});
