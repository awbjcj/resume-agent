import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const quarterlyEvidence = {
  ...matchedEvidence,
  filingCount: 14,
  certifiedCount: 12,
  deniedCount: 2,
  periods: [
    {
      period: "FY2026-Q1",
      filingCount: 10,
      certifiedCount: 9,
      deniedCount: 1,
      wageSummary: { median: 160000 },
    },
    {
      period: "FY2025-Q4",
      filingCount: 4,
      certifiedCount: 3,
      deniedCount: 1,
      wageSummary: { median: 140000 },
    },
  ],
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

    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Historical H-1B sponsorship",
      }),
    ).toBeInTheDocument();
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
    // No per-launch completion callback any more: announcing, acking, and
    // invalidating are owned by the app-root listener, so a run rediscovered
    // without its launch closure still gets all three.
    expect(mocks.trackRun).toHaveBeenCalledWith({
      runId: "run-1",
      kind: "h1bSponsorship",
    });
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

  it("defaults to the latest quarter and plots the cached trend", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: quarterlyEvidence }}
      />,
      { wrapper },
    );

    expect(screen.getByRole("combobox", { name: /period/i })).toHaveTextContent(
      "FY2026 Q1",
    );
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("Three-year filing volume")).toBeInTheDocument();
    expect(screen.getByText("FY2025 Q4: 4 H-1B filings")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /period/i })).toHaveClass(
      "w-full",
      "sm:w-64",
    );
  });

  it("switches figures to one quarter without changing the status banner", async () => {
    const user = userEvent.setup();
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: quarterlyEvidence }}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("combobox", { name: /period/i }));
    await user.click(await screen.findByRole("option", { name: /FY2025 Q4/i }));

    await waitFor(() => expect(screen.getByText("4")).toBeInTheDocument());
    expect(screen.queryByText("10")).not.toBeInTheDocument();
    expect(screen.getByText("Historical filings found")).toBeInTheDocument();
  });

  it("falls back to the newest quarter when a refetch replaces the selected period", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: quarterlyEvidence }}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("combobox", { name: /period/i }));
    await user.click(await screen.findByRole("option", { name: /FY2026 Q1/i }));

    rerender(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{
          capability: "available",
          stale: false,
          evidence: {
            ...quarterlyEvidence,
            filingCount: 4,
            certifiedCount: 3,
            deniedCount: 1,
            periods: [quarterlyEvidence.periods[1]!],
          },
        }}
      />,
    );

    expect(screen.getByRole("combobox", { name: /period/i })).toHaveTextContent(
      "FY2025 Q4",
    );
    expect(screen.getByText("Filings").parentElement).toHaveTextContent("4");
  });

  it("resets the period when navigating to another job with an overlapping period", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: quarterlyEvidence }}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("combobox", { name: /period/i }));
    await user.click(await screen.findByRole("option", { name: /FY2025 Q4/i }));

    rerender(
      <H1BSponsorshipPanel
        jobId={99}
        company="Globex"
        initialResult={{
          capability: "available",
          stale: false,
          evidence: {
            ...quarterlyEvidence,
            filingCount: 20,
            certifiedCount: 17,
            deniedCount: 3,
          },
        }}
      />,
    );

    expect(screen.getByRole("combobox", { name: /period/i })).toHaveTextContent(
      "FY2026 Q1",
    );
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("hides the selector when the provider had no quarterly breakdown", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: matchedEvidence }}
      />,
      { wrapper },
    );

    expect(screen.queryByRole("combobox", { name: /period/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Denied filings")).not.toBeInTheDocument();
    expect(screen.getByText("Historical filings found")).toBeInTheDocument();
  });

  it("marks stale evidence without hiding its figures", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: true, evidence: quarterlyEvidence }}
      />,
      { wrapper },
    );

    expect(screen.getByText(/may be out of date/i)).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeEnabled();
  });

  it("shows stale warning for a legacy flat row too", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: true, evidence: matchedEvidence }}
      />,
      { wrapper },
    );

    expect(screen.getByText(/may be out of date/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /period/i })).not.toBeInTheDocument();
  });

  it("warns that refreshing updates every job at the company", () => {
    render(
      <H1BSponsorshipPanel
        jobId={42}
        company="Acme"
        initialResult={{ capability: "available", stale: false, evidence: quarterlyEvidence }}
      />,
      { wrapper },
    );

    expect(screen.getByText(/updates every job at this company/i)).toBeInTheDocument();
  });
});
