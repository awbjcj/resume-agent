import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

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
  it("shows empty state when no rows", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
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
        }),
      ),
    );
    wrap(<ShortlistContainer />);
    await waitFor(() => expect(screen.getByText("Staff Engineer")).toBeInTheDocument());
    expect(screen.getByText(/Acme/)).toBeInTheDocument();
    // fit score 81 renders (also appears as the single-row "Avg fit" metric)
    expect(screen.getAllByText("81").length).toBeGreaterThan(0);
  });
});
