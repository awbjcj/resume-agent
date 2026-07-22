import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { DashboardPage, heroTitle } from "./DashboardPage";
import { SUMMARY } from "./fixtures";

const READY_STATUS = {
  secrets: { anthropicKey: true, anyLlmKey: true },
  profile: {
    documentCount: 1,
    hasResume: true,
    factsBuiltAt: "2026-07-01T00:00:00Z",
    githubUsername: null,
  },
  search: { configured: true },
  sources: { enabledCount: 2 },
  complete: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
    { wrapper: withQueryClient },
  );
}

describe("heroTitle", () => {
  it("states the actionable total grammatically", () => {
    expect(heroTitle(0)).toBe("Nothing is waiting on you");
    expect(heroTitle(1)).toBe("1 job is waiting on you");
    expect(heroTitle(8)).toBe("8 jobs are waiting on you");
  });
});

describe("DashboardPage", () => {
  it("renders hero total, queue cards, and stage rail from the summary", async () => {
    server.use(
      http.get("/api/dashboard/summary", () => HttpResponse.json(SUMMARY)),
      http.get("/api/setup/status", () => HttpResponse.json(READY_STATUS)),
    );
    renderPage();
    // queues sum: 2 + 4 + 1 + 1
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "8 jobs are waiting on you" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("link", { name: /approve 4/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Pipeline stages")).toBeInTheDocument();
    expect(screen.getByText(/recent runs/i)).toBeInTheDocument();
  });

  it("guides a fresh install with the getting-started checklist, not the drained-funnel card", async () => {
    const zero = Object.fromEntries(
      Object.keys(SUMMARY.statusCounts).map((k) => [k, 0]),
    );
    server.use(
      http.get("/api/dashboard/summary", () =>
        HttpResponse.json({
          statusCounts: zero,
          queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
          applied: 0,
        }),
      ),
      http.get("/api/setup/status", () =>
        HttpResponse.json({
          ...READY_STATUS,
          complete: false,
          sources: { enabledCount: 0 },
        }),
      ),
    );
    renderPage();
    // The onboarding checklist owns first-run guidance...
    await waitFor(() =>
      expect(screen.getByText("Getting started")).toBeInTheDocument(),
    );
    // ...the "next step" (sources not enabled) is surfaced as a real CTA...
    const sourceLinks = screen.getAllByRole("link", { name: /add sources/i });
    expect(sourceLinks.length).toBeGreaterThan(0);
    expect(sourceLinks[0]).toHaveAttribute("href", "/settings/sources");
    // ...and the populated funnel does not show.
    expect(screen.queryByLabelText("Pipeline stages")).not.toBeInTheDocument();
  });

  it("does not treat an only-rejected funnel as populated", async () => {
    // rejected doesn't appear on the rail/queues, so a naive "sum every
    // statusCount" emptiness check would wrongly treat this as populated. Even
    // for a set-up user, an all-rejected funnel has no active jobs, so the
    // funnel view stays hidden and guidance points forward instead.
    server.use(
      http.get("/api/dashboard/summary", () =>
        HttpResponse.json({
          statusCounts: {
            raw: 0, extracted: 0, filtered: 0, rejected: 5,
            shortlisted: 0, approved: 0, tailored: 0, rendered: 0,
          },
          queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
          applied: 0,
        }),
      ),
      http.get("/api/setup/status", () => HttpResponse.json(READY_STATUS)),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByLabelText("Job-search journey")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Pipeline stages")).not.toBeInTheDocument();
  });
});
