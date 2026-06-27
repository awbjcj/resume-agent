import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { MatchGapContainer } from "./MatchGapContainer";

const wrap = (ui: ReactNode) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
};

const populated = {
  targetTotal: 2,
  clustersStale: false,
  jobs: [
    { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
    { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
  ],
  skills: [
    { skill: "Kubernetes", themeId: "infra", covered: false },
    { skill: "Terraform", themeId: "infra", covered: false },
  ],
  edges: [
    { jobId: 1, skill: "Kubernetes", source: "must" },
    { jobId: 2, skill: "Kubernetes", source: "tech" },
    { jobId: 2, skill: "Terraform", source: "must" },
  ],
  themes: [{ id: "infra", label: "Cloud / Infrastructure" }],
};

describe("MatchGapContainer", () => {
  it("opens the demanding jobs drawer from a skill action", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json(populated)));
    wrap(<MatchGapContainer />);

    const skillActions = await screen.findAllByRole("button", { name: /Kubernetes, gap/ });
    await userEvent.click(skillActions[0]);

    const drawer = await screen.findByRole("dialog");
    await waitFor(() => expect(within(drawer).getByText("Stripe")).toBeInTheDocument());
    expect(within(drawer).getByText("Datadog")).toBeInTheDocument();
  });

  it("opens a theme with the union of its demanding jobs", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json(populated)));
    wrap(<MatchGapContainer />);

    await userEvent.click(
      await screen.findByRole("button", { name: /open Cloud \/ Infrastructure learning path/i }),
    );

    const drawer = screen.getByRole("dialog");
    expect(within(drawer).getByRole("heading", { name: "Cloud / Infrastructure" })).toBeInTheDocument();
    expect(within(drawer).getByText("Stripe")).toBeInTheDocument();
    expect(within(drawer).getByText("Datadog")).toBeInTheDocument();
  });

  it("shows the empty state when there are no target jobs", async () => {
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({
          targetTotal: 0,
          clustersStale: false,
          jobs: [],
          skills: [],
          edges: [],
          themes: [],
        }),
      ),
    );
    wrap(<MatchGapContainer />);

    expect(await screen.findByText(/no target jobs yet/i)).toBeInTheDocument();
  });

  it("shows a request error with a retry action", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json({}, { status: 500 })));
    wrap(<MatchGapContainer />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't load skill demand/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("has no axe violations when populated", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json(populated)));
    const { container } = wrap(<MatchGapContainer />);
    await screen.findByText("Ranked demand");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
