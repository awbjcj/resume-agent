import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    await waitFor(() => expect(screen.getByText("Eng")).toBeInTheDocument());
    expect(screen.queryByText(/1 selected/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /select acme eng/i }));
    expect(screen.getByText(/1 selected/i)).toBeInTheDocument();
  });
});
