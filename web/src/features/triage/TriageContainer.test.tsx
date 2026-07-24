import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { TriageContainer } from "./TriageContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("TriageContainer", () => {
  it("selecting a row enables Archive selected", async () => {
    server.use(
      http.get("/api/triage", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 3,
              company: "Acme",
              title: "Eng",
              location: "NYC",
              source: "adzuna",
              status: "raw",
              fitScore: 40,
              postedAt: null,
              archivedAt: null,
              hasProgress: false,
              url: "https://example.test/job/3",
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
          facets: { source: { adzuna: 1 }, status: { raw: 1 } },
          total: 1,
        }),
      ),
      http.post("/api/jobs/bulk", () =>
        HttpResponse.json({ affected: 1, skipped: 0, reasons: {} }),
      ),
    );
    wrap(<TriageContainer />);
    const rowCheckbox = await screen.findByRole("checkbox", { name: /select acme eng/i });
    expect(screen.queryByRole("status", { name: /1 selected/i })).not.toBeInTheDocument();
    fireEvent.click(rowCheckbox);
    await waitFor(() =>
      expect(screen.getByRole("status", { name: /1 selected/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Open posting" })).toHaveAttribute("href", "https://example.test/job/3");
    expect(screen.getByRole("button", { name: "Archive job" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete job" })).toBeInTheDocument();
    expect(screen.queryByText("Fit")).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Rejection reason" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Minimum fit")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Minimum salary")).not.toBeInTheDocument();
  });

  it("shows a rejected job's reason in a compact labeled note", async () => {
    server.use(
      http.get("/api/triage", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 4,
              company: "Acme",
              title: "Principal Engineer",
              location: "Remote",
              source: "adzuna",
              status: "rejected",
              fitScore: 31,
              postedAt: null,
              archivedAt: null,
              hasProgress: false,
              rejectReason:
                "The role requires on-site work and does not offer the required sponsorship.",
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
          facets: { source: { adzuna: 1 }, status: { rejected: 1 } },
          total: 1,
        }),
      ),
    );

    wrap(<TriageContainer />);

    expect(
      await screen.findByLabelText(
        "Rejection reason: The role requires on-site work and does not offer the required sponsorship.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The role requires on-site work and does not offer the required sponsorship.",
      ),
    ).toBeInTheDocument();
  });
});
