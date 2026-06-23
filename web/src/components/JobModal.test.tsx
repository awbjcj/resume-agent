import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { JobModal } from "./JobModal";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

const jobPayload = (overrides: Record<string, unknown> = {}) => ({
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
  skills: [],
  ...overrides,
});

describe("JobModal", () => {
  it("renders job detail with a heading and the JD text", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /staff engineer/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Build things.")).toBeInTheDocument();
  });

  it("groups skills into must-have / best-have with a coverage tally", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json(
          jobPayload({
            skills: [
              { name: "Python", covered: true, required: true },
              { name: "Kafka", covered: false, required: true },
              { name: "Rust", covered: false, required: false },
            ],
          }),
        ),
      ),
    );
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("Must-have")).toBeInTheDocument());
    expect(screen.getByText("Best-have")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Rust")).toBeInTheDocument();
    expect(screen.getByText("1/3 covered")).toBeInTheDocument();
  });
});
