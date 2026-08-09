import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { useApprovedLaunchJobs } from "./use-approved-launch-jobs";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
  );
}

describe("useApprovedLaunchJobs", () => {
  it("loads every approved pipeline page", async () => {
    const pages: number[] = [];
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? "1");
        pages.push(page);
        return HttpResponse.json({
          data: [
            {
              jobId: page,
              company: `Company ${page}`,
              title: `Role ${page}`,
              status: "approved",
            },
          ],
          pagination: { page, pageSize: 200, totalItems: 2, totalPages: 2 },
          total: 2,
        });
      }),
    );

    const { result } = renderHook(() => useApprovedLaunchJobs(true), { wrapper });

    await waitFor(() => expect(result.current.jobs).toHaveLength(2));
    expect(pages).toEqual([1, 2]);
    expect(result.current.jobs.map((job) => job.jobId)).toEqual([1, 2]);
  });

  it("loads approved and completed tailoring stages for cover letters", async () => {
    let requestedStatus: string | null = null;
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        requestedStatus = new URL(request.url).searchParams.get("status");
        return HttpResponse.json({
          data: [
            { jobId: 1, company: "Approved Co", title: "One", status: "approved" },
            { jobId: 2, company: "Tailored Co", title: "Two", status: "tailored" },
            { jobId: 3, company: "Rendered Co", title: "Three", status: "rendered" },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 3, totalPages: 1 },
          total: 3,
        });
      }),
    );

    const { result } = renderHook(() => useApprovedLaunchJobs(true, true), { wrapper });

    await waitFor(() => expect(result.current.jobs).toHaveLength(3));
    expect(requestedStatus).toBe("approved,tailored,rendered");
  });
});
