import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { JobDrawer } from "./JobDrawer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("JobDrawer", () => {
  it("renders job detail with a heading and the JD text", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json({
          id: 42,
          source: "greenhouse",
          url: null,
          company: "Acme",
          title: "Staff Engineer",
          location: "Remote",
          jdText: "Build things.",
          status: "approved",
          fitScore: 80,
          fitRationale: "Strong match.",
          criteriaJson: null,
          postedAt: null,
          archivedAt: null,
          createdAt: "2026-06-01T00:00:00Z",
          hasProgress: false,
          application: null,
          resumeVersions: [],
        }),
      ),
    );
    wrap(<JobDrawer jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    expect(screen.getByText("Build things.")).toBeInTheDocument();
  });
});
