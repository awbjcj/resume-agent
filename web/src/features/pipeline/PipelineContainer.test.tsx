import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

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

const pipelineItem = (jobId: number, status: string, title: string) => ({
  jobId,
  company: `${status} Co`,
  title,
  status,
  fitScore: 80,
  jdText: `${status} description`,
  critiqueJson: null,
  pdfPath: null,
  applicationStatus: null,
  hasProgress: status === "tailored" || status === "rendered",
});

describe("PipelineContainer", () => {
  beforeEach(() => localStorage.clear());
  it("opens tailoring with the complete approved-job query", async () => {
    const requestedStatuses: Array<string | null> = [];
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        const status = new URL(request.url).searchParams.get("status");
        requestedStatuses.push(status);
        const approved = status === "approved";
        return HttpResponse.json({
          data: approved ? [pipelineItem(7, "approved", "Platform Engineer")] : [],
          pagination: { page: 1, pageSize: 200, totalItems: approved ? 1 : 0, totalPages: 1 },
          facets: { status: { approved: 1 } },
          total: approved ? 1 : 0,
        });
      }),
    );
    const user = userEvent.setup();
    wrap(<PipelineContainer />);
    await screen.findByText("No jobs in the pipeline");

    await user.click(screen.getByRole("button", { name: /tailor approved/i }));

    expect(await screen.findByRole("heading", { name: "Tailor resumes" })).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: /Platform Engineer/ })).toBeChecked();
    expect(requestedStatuses).toContain("approved");
  });

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
    await waitFor(() => expect(screen.getByText("Dev")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /approved.*1 job/i }));
    // each stage label appears in both the section header and a card badge
    expect(screen.getAllByText(/approved/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/rendered/i).length).toBeGreaterThan(0);
    expect(screen.getByText("fit 70")).toBeInTheDocument();
    expect(screen.getByText("fit 88")).toBeInTheDocument();
    expect(screen.getByText(/Remote eligible Mid/)).toBeInTheDocument();
    expect(screen.queryByText(/corporate/)).not.toBeInTheDocument();
    expect(screen.queryByText(/laptop/)).not.toBeInTheDocument();
  });

  it("renders quick actions in per-stage list view", async () => {
    localStorage.setItem("pipeline-view", "list");
    server.use(http.get("/api/pipeline", () => HttpResponse.json({
      data: [{ ...pipelineItem(9, "tailored", "Operator"), url: "https://example.test/9" }],
      pagination: { page: 1, pageSize: 50, totalItems: 1, totalPages: 1 },
      facets: { status: { tailored: 1 } }, total: 1,
    })));
    wrap(<PipelineContainer />);
    expect(await screen.findByRole("button", { name: "Archive job" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open posting" })).toBeInTheDocument();
  });

  it("selects every job in a stage from the list header checkbox", async () => {
    localStorage.setItem("pipeline-view", "list");
    server.use(http.get("/api/pipeline", () => HttpResponse.json({
      data: [
        pipelineItem(9, "tailored", "Operator"),
        pipelineItem(10, "tailored", "Architect"),
      ],
      pagination: { page: 1, pageSize: 50, totalItems: 2, totalPages: 1 },
      facets: { status: { tailored: 2 } }, total: 2,
    })));
    const user = userEvent.setup();
    wrap(<PipelineContainer />);
    const selectAll = await screen.findByRole("checkbox", { name: "Select all loaded jobs" });

    await user.click(selectAll);

    expect(screen.getByRole("checkbox", { name: /Select tailored Co Operator/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Select tailored Co Architect/ })).toBeChecked();
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
    expect(stageHeadings.map((heading) => heading.textContent)).toEqual(["Tailored", "Raw"]);
  });

  it("orders stages by post-processing priority and collapses inactive groups", async () => {
    server.use(
      http.get("/api/pipeline", () =>
        HttpResponse.json({
          data: [
            pipelineItem(1, "raw", "Raw role"),
            pipelineItem(2, "approved", "Approved role"),
            pipelineItem(3, "rendered", "Rendered role"),
            pipelineItem(4, "tailored", "Tailored role"),
            pipelineItem(5, "screening", "Screening role"),
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 5, totalPages: 1 },
          facets: {
            status: { raw: 1, approved: 1, rendered: 1, tailored: 1, screening: 1 },
          },
          total: 5,
        }),
      ),
    );
    const user = userEvent.setup();

    wrap(<PipelineContainer />);

    const tailored = await screen.findByRole("button", { name: /tailored.*1 job/i });
    const rendered = screen.getByRole("button", { name: /rendered.*1 job/i });
    const approved = screen.getByRole("button", { name: /approved.*1 job/i });
    const stageHeadings = screen.getAllByRole("heading", { level: 2 });

    expect(stageHeadings.map((heading) => heading.textContent)).toEqual([
      "Tailored",
      "Rendered",
      "Approved",
      "Raw",
      "Screening",
    ]);
    expect(tailored).toHaveAttribute("aria-expanded", "true");
    expect(rendered).toHaveAttribute("aria-expanded", "true");
    expect(approved).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Tailored role")).toBeInTheDocument();
    expect(screen.getByText("Rendered role")).toBeInTheDocument();
    expect(screen.queryByText("Approved role")).not.toBeInTheDocument();
    expect(screen.queryByText("Raw role")).not.toBeInTheDocument();
    expect(screen.queryByText("Screening role")).not.toBeInTheDocument();

    await user.click(approved);
    expect(screen.getByText("Approved role")).toBeInTheDocument();
    await user.click(approved);
    expect(screen.queryByText("Approved role")).not.toBeInTheDocument();
  });

  it("filters the pipeline by multiple statuses through the server query", async () => {
    const requestedStatuses: Array<string | null> = [];
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        requestedStatuses.push(new URL(request.url).searchParams.get("status"));
        return HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 1 },
          facets: { status: { tailored: 1, rendered: 1 } },
          total: 0,
        });
      }),
    );
    const user = userEvent.setup();

    wrap(<PipelineContainer />);
    await screen.findByText("No jobs in the pipeline");
    await user.click(screen.getByRole("button", { name: "Status" }));
    await user.click(screen.getByRole("checkbox", { name: /tailored/i }));
    await user.click(screen.getByRole("checkbox", { name: /rendered/i }));

    await waitFor(() => expect(requestedStatuses.at(-1)).toBe("tailored,rendered"));
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
    await user.click(screen.getByRole("button", { name: /^apply$/i }));

    await waitFor(() => expect(requestedMinFits.at(-1)).toBe("65"));
  });
});
