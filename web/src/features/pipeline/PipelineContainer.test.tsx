import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { PipelineContainer } from "./PipelineContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("PipelineContainer", () => {
  it("groups cards by stage", async () => {
    server.use(
      http.get("/api/pipeline", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 1,
              company: "A",
              title: "Eng",
              status: "approved",
              fitScore: 70,
              jdText: "x",
              critiqueJson: null,
              pdfPath: null,
              applicationStatus: null,
              hasProgress: false,
            },
            {
              jobId: 2,
              company: "B",
              title: "Dev",
              status: "rendered",
              fitScore: 88,
              jdText: "y",
              critiqueJson: null,
              pdfPath: null,
              applicationStatus: null,
              hasProgress: true,
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 2, totalPages: 1 },
          facets: { status: { approved: 1, rendered: 1 } },
          total: 2,
        }),
      ),
    );
    wrap(<PipelineContainer />);
    await waitFor(() => expect(screen.getByText("Eng")).toBeInTheDocument());
    // each stage label appears in both the section header and a card badge
    expect(screen.getAllByText(/approved/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/rendered/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Dev")).toBeInTheDocument();
  });
});
