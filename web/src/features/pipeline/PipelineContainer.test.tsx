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
  jdPreview: `${status} description`,
  critiqueJson: null,
  pdfPath: null,
  applicationStatus: null,
  hasProgress: status === "tailored" || status === "rendered",
});

// Each stage section fetches its own rows with a `status` filter, while the
// container's overview query (no status) supplies facets + total. This handler
// mirrors that contract: facets always reflect the whole dataset, rows are only
// returned for status-scoped section queries.
const statusAware = (dataset: Array<Record<string, unknown>>) =>
  http.get("/api/pipeline", ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    const wanted = status ? new Set(status.split(",")) : null;
    const counts: Record<string, number> = {};
    for (const item of dataset) {
      const key = item.status as string;
      counts[key] = (counts[key] ?? 0) + 1;
    }
    const rows = wanted ? dataset.filter((item) => wanted.has(item.status as string)) : [];
    return HttpResponse.json({
      data: rows,
      pagination: { page: 1, pageSize: 20, totalItems: rows.length, totalPages: 1 },
      facets: { status: counts },
      total: wanted ? rows.length : dataset.length,
    });
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
          // The overview query (no status) sees an empty board; only the
          // launch dialog's status=approved query surfaces the approved job.
          facets: { status: approved ? { approved: 1 } : {} },
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
      statusAware([
        {
          jobId: 1,
          company: "A",
          title: "Eng",
          status: "approved",
          fitScore: 70,
          jdPreview: "Google Google San Francisco, CA Remote eligible Mid",
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
          jdPreview: "y",
          critiqueJson: null,
          pdfPath: null,
          applicationStatus: null,
          hasProgress: true,
        },
      ]),
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
    server.use(
      statusAware([{ ...pipelineItem(9, "tailored", "Operator"), url: "https://example.test/9" }]),
    );
    wrap(<PipelineContainer />);
    expect(await screen.findByRole("button", { name: "Archive job" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open posting" })).toBeInTheDocument();
  });

  it("shows a compact details column with filtered reasons in list view", async () => {
    localStorage.setItem("pipeline-view", "list");
    const user = userEvent.setup();
    server.use(
      statusAware([
        {
          ...pipelineItem(11, "filtered", "Platform Engineer"),
          rejectReason: "sponsorship not available",
          rejectCategory: "filtered",
          sponsorshipSignal: "denied",
          employmentType: "full_time",
        },
      ]),
    );

    wrap(<PipelineContainer />);

    await user.click(await screen.findByRole("button", { name: /filtered.*1 job/i }));
    expect(await screen.findByText("Details")).toBeInTheDocument();
    expect(screen.getByLabelText("Filtered: sponsorship not available")).toBeInTheDocument();
  });

  it("selects every job in a stage from the list header checkbox", async () => {
    localStorage.setItem("pipeline-view", "list");
    server.use(
      statusAware([
        pipelineItem(9, "tailored", "Operator"),
        pipelineItem(10, "tailored", "Architect"),
      ]),
    );
    const user = userEvent.setup();
    wrap(<PipelineContainer />);
    const selectAll = await screen.findByRole("checkbox", { name: "Select all loaded jobs" });

    await user.click(selectAll);

    expect(screen.getByRole("checkbox", { name: /Select tailored Co Operator/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Select tailored Co Architect/ })).toBeChecked();
  });

  it("puts the tailored stage before every other status", async () => {
    server.use(
      statusAware([
        {
          jobId: 1,
          company: "Raw Co",
          title: "Raw role",
          status: "raw",
          fitScore: 40,
          jdPreview: "raw",
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
          jdPreview: "tailored",
          critiqueJson: [],
          pdfPath: null,
          applicationStatus: null,
          hasProgress: true,
        },
      ]),
    );

    wrap(<PipelineContainer />);
    await waitFor(() => expect(screen.getByText("Tailored role")).toBeInTheDocument());

    const stageHeadings = screen.getAllByRole("heading", { level: 2 });
    expect(stageHeadings.map((heading) => heading.textContent)).toEqual(["Tailored", "Raw"]);
  });

  it("orders stages by post-processing priority and collapses inactive groups", async () => {
    server.use(
      statusAware([
        pipelineItem(1, "raw", "Raw role"),
        pipelineItem(2, "approved", "Approved role"),
        pipelineItem(3, "rendered", "Rendered role"),
        pipelineItem(4, "tailored", "Tailored role"),
        pipelineItem(5, "screening", "Screening role"),
      ]),
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
    // Open stages fetch their rows independently, so await the first arrival.
    expect(await screen.findByText("Tailored role")).toBeInTheDocument();
    expect(await screen.findByText("Rendered role")).toBeInTheDocument();
    expect(screen.queryByText("Approved role")).not.toBeInTheDocument();
    expect(screen.queryByText("Raw role")).not.toBeInTheDocument();
    expect(screen.queryByText("Screening role")).not.toBeInTheDocument();

    await user.click(approved);
    expect(await screen.findByText("Approved role")).toBeInTheDocument();
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
          // Empty facets keep the board in its empty state so only the overview
          // query runs — the test asserts on the status param it carries.
          facets: { status: {} },
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

  it("applies sponsorship and type facets through the pipeline server query", async () => {
    const requestedFilters: Array<{
      sponsorship: string | null;
      employmentType: string | null;
    }> = [];
    server.use(
      http.get("/api/pipeline", ({ request }) => {
        const search = new URL(request.url).searchParams;
        requestedFilters.push({
          sponsorship: search.get("sponsorship"),
          employmentType: search.get("employmentType"),
        });
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

    await user.click(screen.getByRole("button", { name: "Sponsorship" }));
    await user.click(screen.getByRole("checkbox", { name: /offered/i }));
    await user.click(screen.getByRole("button", { name: "Type" }));
    await user.click(screen.getByRole("checkbox", { name: /full time/i }));

    await waitFor(() =>
      expect(requestedFilters.at(-1)).toEqual({
        sponsorship: "offered",
        employmentType: "full_time",
      }),
    );
  });

  it("opens redo for the current selection with re-tailor pre-ticked", async () => {
    const user = userEvent.setup();
    localStorage.setItem("pipeline-view", "list");
    server.use(
      statusAware([
        pipelineItem(9, "tailored", "Operator"),
        pipelineItem(10, "rendered", "Architect"),
      ]),
    );
    wrap(<PipelineContainer />);

    await user.click(
      await screen.findByRole("checkbox", { name: /Select tailored Co Operator/ }),
    );
    await user.click(screen.getByRole("button", { name: /^redo/i }));

    expect(
      await screen.findByRole("checkbox", { name: /re-tailor resume/i }),
    ).toBeChecked();
    expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
  });

  it("allows redo on a rendered job", async () => {
    const user = userEvent.setup();
    localStorage.setItem("pipeline-view", "list");
    server.use(statusAware([pipelineItem(10, "rendered", "Architect")]));
    wrap(<PipelineContainer />);

    await user.click(
      await screen.findByRole("checkbox", { name: /Select rendered Co Architect/ }),
    );
    await user.click(screen.getByRole("button", { name: /^redo/i }));

    expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
  });
});
