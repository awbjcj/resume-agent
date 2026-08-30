import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";
import { CompanyIntelligencePanel } from "./CompanyIntelligencePanel";

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

const evidence = {
  normalizedCompany: "acme",
  displayCompany: "Acme",
  overview: "Acme builds infrastructure software.",
  insights: [
    {
      axis: "strategy" as const,
      summary: "Acme is investing in platform tooling.",
      whyItMatters: "Ask how the role supports the platform strategy.",
      citations: ["https://acme.example/strategy"],
    },
  ],
  sources: [
    {
      title: "Acme strategy",
      url: "https://acme.example/strategy",
      publisher: "Acme",
      sourceType: "official" as const,
    },
  ],
  retrievedAt: "2026-08-29T12:00:00Z",
  expiresAt: "2026-09-28T12:00:00Z",
  caveat: "Verify important claims with the linked sources.",
};

const readyResult = {
  state: "ready" as const,
  reason: null,
  canRefresh: true as const,
  capability: "available" as const,
  stale: false,
  isStale: false,
  evidence,
};

describe("CompanyIntelligencePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("renders saved insights, source provenance, and caveat", () => {
    render(
      <CompanyIntelligencePanel
        jobId={42}
        company="Acme"
        initialResult={readyResult}
      />,
      { wrapper },
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "Company intelligence" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme builds infrastructure software.")).toBeInTheDocument();
    expect(screen.getByText("Acme is investing in platform tooling.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /acme strategy/i })).toHaveLength(1);
    expect(screen.getByRole("link", { name: /open source/i })).toHaveAttribute(
      "href",
      "https://acme.example/strategy",
    );
    expect(screen.getByText(/verify important claims/i)).toBeInTheDocument();
  });

  it("has no automated accessibility violations", async () => {
    const { container } = render(
      <CompanyIntelligencePanel
        jobId={42}
        company="Acme"
        initialResult={readyResult}
      />,
      { wrapper },
    );

    expect((await axe(container)).violations).toEqual([]);
  });

  it("keeps stale evidence visible and explains explicit refresh", () => {
    render(
      <CompanyIntelligencePanel
        jobId={42}
        company="Acme"
        initialResult={{ ...readyResult, stale: true, isStale: true }}
      />,
      { wrapper },
    );

    expect(screen.getByText("May be outdated")).toBeInTheDocument();
    expect(screen.getByText(/remains visible until you choose to refresh/i)).toBeInTheDocument();
    expect(screen.getByText("Acme builds infrastructure software.")).toBeInTheDocument();
  });

  it("launches an explicit company-scoped research run", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/jobs/42/company-intelligence/refreshes", () =>
        HttpResponse.json(
          { runId: "run-company", kind: "companyIntelligence", meta: { jobId: 42 } },
          { status: 202 },
        ),
      ),
    );
    render(
      <CompanyIntelligencePanel
        jobId={42}
        company="Acme"
        initialResult={{
          state: "empty",
          reason: "not_researched",
          canRefresh: true,
          capability: "unavailable",
          stale: false,
          isStale: false,
          evidence: null,
          message: "No company research has been saved yet.",
        }}
      />,
      { wrapper },
    );

    const button = screen.getByRole("button", {
      name: /research company for acme/i,
    });
    await user.tab();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /researching… for acme/i })).toBeDisabled(),
    );
    expect(mocks.trackRun).toHaveBeenCalledWith({
      runId: "run-company",
      kind: "companyIntelligence",
    });
  });

  it("shows a failed run without hiding the last good dossier", () => {
    useRunStore.getState().upsert({
      runId: "run-failed",
      kind: "companyIntelligence",
      status: "failed",
      percent: 0,
      phase: "Failed",
      current: 0,
      total: 0,
      etaText: null,
      error: "research provider unavailable",
      meta: { jobId: 42 },
    });

    render(
      <CompanyIntelligencePanel
        jobId={42}
        company="Acme"
        initialResult={readyResult}
      />,
      { wrapper },
    );

    expect(screen.getByRole("alert")).toHaveTextContent("research provider unavailable");
    expect(screen.getByText("Acme builds infrastructure software.")).toBeInTheDocument();
  });
});
