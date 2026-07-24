import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { ShortlistContainer } from "./ShortlistContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("ShortlistContainer", () => {
  beforeEach(() => localStorage.clear());
  it("shows empty state when no rows", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
          facets: {},
          total: 0,
        }),
      ),
    );
    wrap(<ShortlistContainer />);
    await waitFor(() =>
      expect(screen.getByText(/nothing shortlisted yet/i)).toBeInTheDocument(),
    );
  });

  it("renders a card per row", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 7,
              company: "Acme",
              title: "Staff Engineer",
              location: "Remote",
              fitScore: 81,
              skills: [],
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
          facets: { skills: {} },
          total: 1,
        }),
      ),
    );
    wrap(<ShortlistContainer />);
    await waitFor(() => expect(screen.getByText("Staff Engineer")).toBeInTheDocument());
    expect(screen.getByText(/Acme/)).toBeInTheDocument();
    // fit score 81 renders (also appears as the single-row "Avg fit" metric)
    expect(screen.getAllByText("81").length).toBeGreaterThan(0);
  });

  it("switches to a list while retaining row actions", async () => {
    localStorage.setItem("shortlist-view", "list");
    server.use(http.get("/api/shortlist", () => HttpResponse.json({
      data: [{
        jobId: 8,
        company: "Acme",
        title: "Designer",
        fitScore: 70,
        skills: [],
        url: "https://example.test/8",
        salaryMin: 120000,
        salaryMax: 150000,
        salaryCurrency: "USD",
        seniority: "Senior",
        employmentType: "Full-time",
        industry: "Design software",
      }],
      pagination: { page: 1, pageSize: 50, totalItems: 1, totalPages: 1 }, facets: {}, total: 1,
    })));
    wrap(<ShortlistContainer />);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open posting" })).toBeInTheDocument();
    expect(screen.getByLabelText("Job details")).toBeInTheDocument();
    expect(screen.getByText("$120k–150k")).toBeInTheDocument();
    expect(screen.getByText("Design software")).toBeInTheDocument();
    expect(screen.queryByText("Level")).not.toBeInTheDocument();
    expect(screen.queryByText("Work type")).not.toBeInTheDocument();
  });

  it("keeps the open facet scope stable after filtered results finish loading", async () => {
    const user = userEvent.setup();
    const requestedSources: Array<string | null> = [];
    server.use(
      http.get("/api/shortlist", ({ request }) => {
        const source = new URL(request.url).searchParams.get("source");
        requestedSources.push(source);
        return HttpResponse.json({
          data: [
            {
              jobId: 7,
              company: "Acme",
              title: "Staff Engineer",
              location: "Remote",
              fitScore: 81,
              skills: [],
            },
          ],
          pagination: { page: 1, pageSize: 50, totalItems: source ? 1 : 2, totalPages: 1 },
          facets: { source: source ? { greenhouse: 1 } : { greenhouse: 1, lever: 1 } },
          total: source ? 1 : 2,
        });
      }),
    );
    wrap(<ShortlistContainer />);
    await screen.findByText("Staff Engineer");

    await user.click(screen.getByRole("button", { name: "Source" }));
    await user.click(screen.getByRole("checkbox", { name: /greenhouse/i }));

    expect((await screen.findAllByText("1 matching")).length).toBeGreaterThan(0);
    expect(screen.getByText("Filter by Source")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /lever/i }));
    await waitFor(() =>
      expect(requestedSources.at(-1)).toBe("greenhouse,lever"),
    );
  });
});
