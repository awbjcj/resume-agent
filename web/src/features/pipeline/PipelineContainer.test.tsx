import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
              jdText:
                "Google \\_corporate\\_fare\\_ Google \\_place\\_ San Francisco, CA " +
                "\\_laptop\\_windows\\_ Remote eligible \\*\\*Mid\\*\\*",
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
    expect(screen.getByText("fit 70")).toBeInTheDocument();
    expect(screen.getByText("fit 88")).toBeInTheDocument();
    expect(screen.getByText(/Remote eligible Mid/)).toBeInTheDocument();
    expect(screen.queryByText(/corporate/)).not.toBeInTheDocument();
    expect(screen.queryByText(/laptop/)).not.toBeInTheDocument();
    expect(screen.getByText("Dev")).toBeInTheDocument();
  });

  it("puts the tailored stage before every other status", async () => {
    server.use(
      http.get("/api/pipeline", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 1,
              company: "Raw Co",
              title: "Raw role",
              status: "raw",
              fitScore: 40,
              jdText: "raw",
              critiqueJson: null,
              pdfPath: null,
              applicationStatus: null,
              hasProgress: false,
            },
            {
              jobId: 2,
              company: "Tailored Co",
              title: "Tailored role",
              status: "tailored",
              fitScore: 90,
              jdText: "tailored",
              critiqueJson: [],
              pdfPath: null,
              applicationStatus: null,
              hasProgress: true,
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 2, totalPages: 1 },
          facets: { status: { raw: 1, tailored: 1 } },
          total: 2,
        }),
      ),
    );

    wrap(<PipelineContainer />);
    await waitFor(() => expect(screen.getByText("Tailored role")).toBeInTheDocument());

    const stageHeadings = screen.getAllByRole("heading", { level: 2 });
    expect(stageHeadings.map((heading) => heading.textContent)).toEqual(["tailored", "raw"]);
  });

  it("filters the pipeline by status through the server query", async () => {
    const requestedStatuses: Array<string | null> = [];
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        requestedStatuses.push(new URL(request.url).searchParams.get("status"));
        return HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 1 },
          facets: { status: {} },
          total: 0,
        });
      }),
    );
    const user = userEvent.setup();

    wrap(<PipelineContainer />);
    await screen.findByText("No jobs in the pipeline");
    await user.click(screen.getByRole("combobox", { name: "Status" }));
    await user.click(screen.getByRole("option", { name: "Tailored" }));

    await waitFor(() => expect(requestedStatuses.at(-1)).toBe("tailored"));
  });

  it("applies min fit from a numeric input", async () => {
    const requestedMinFits: Array<string | null> = [];
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        requestedMinFits.push(new URL(request.url).searchParams.get("minFit"));
        return HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 1 },
          facets: { status: {} },
          total: 0,
        });
      }),
    );
    const user = userEvent.setup();

    wrap(<PipelineContainer />);
    await screen.findByText("No jobs in the pipeline");
    const minFit = screen.getByRole("spinbutton", { name: "Min fit" });
    await user.type(minFit, "65");
    await user.click(screen.getByRole("button", { name: /apply filters/i }));

    await waitFor(() => expect(requestedMinFits.at(-1)).toBe("65"));
  });
});
