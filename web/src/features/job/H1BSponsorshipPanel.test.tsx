import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { useRunStore } from "@/lib/runs/store";
import { H1BSponsorshipPanel } from "./H1BSponsorshipPanel";

const mocks = vi.hoisted(() => ({ trackRun: vi.fn() }));
vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const matchedEvidence = {
  status: "matched" as const,
  normalizedCompany: "acme",
  displayCompany: "Acme",
  fiscalPeriods: ["2022", "2023"],
  filingCount: 12,
  certifiedCount: 8,
  wageSummary: { median: 150000, p75: 180000 },
  sourceUrl: "https://example.com/acme",
  dataVersion: "fixture-v1",
  retrievedAt: "2026-08-03T12:00:00Z",
  expiresAt: "2026-09-02T12:00:00Z",
  confidence: 0.82,
  caveat:
    "Historical H-1B filings do not confirm current sponsorship for this role or current employer policy.",
};

describe("H1BSponsorshipPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("formats evidence carried on the persisted job detail", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: matchedEvidence }}
      />,
      { wrapper },
    );

    expect(screen.getByText("Historical filings found")).toBeInTheDocument();
    expect(screen.getByText("2022, 2023")).toBeInTheDocument();
    expect(screen.getByText("$150,000")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open source record/i })).toHaveAttribute(
      "href",
      "https://example.com/acme",
    );
    expect(screen.getByText(/historical h-1b filings do not confirm/i)).toBeInTheDocument();
  });

  it("launches a background check and shows the active state", async () => {
    server.use(
      http.post("/api/jobs/42/h1b-sponsorship", () =>
        HttpResponse.json({ runId: "run-1", kind: "h1bSponsorship" }, { status: 202 }),
      ),
    );

    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{
          capability: "unavailable",
          stale: false,
          message: "No H-1B evidence has been checked for this job yet.",
          evidence: null,
        }}
      />,
      { wrapper },
    );

    fireEvent.click(
      screen.getByRole("button", { name: /check h-1b for h-1b sponsorship/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /checking… for h-1b sponsorship/i }),
      ).toBeDisabled(),
    );
    expect(mocks.trackRun).toHaveBeenCalledWith(
      { runId: "run-1", kind: "h1bSponsorship" },
      expect.any(Function),
    );
  });

  it("shows a failure banner when the h1bSponsorship run fails", () => {
    useRunStore.getState().upsert({
      runId: "run-2",
      kind: "h1bSponsorship",
      status: "failed",
      percent: 0,
      phase: "Failed",
      current: 0,
      total: 0,
      etaText: null,
      error: "provider unavailable",
      meta: { jobId: 42 },
    });

    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{
          capability: "unavailable",
          stale: false,
          message: "No H-1B evidence has been checked for this job yet.",
          evidence: null,
        }}
      />,
      { wrapper },
    );

    expect(screen.getByText("provider unavailable")).toBeInTheDocument();
  });

  it("explains disabled research and keeps the action unavailable", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{
          capability: "disabled",
          stale: false,
          message: "H-1B research is disabled for this workspace.",
          evidence: null,
        }}
      />,
      { wrapper },
    );

    expect(screen.getByRole("button", { name: /h-1b disabled/i })).toBeDisabled();
    expect(screen.getByText(/research is disabled for this workspace/i)).toBeInTheDocument();
  });
});
