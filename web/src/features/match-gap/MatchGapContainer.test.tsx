import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { MatchGapContainer } from "./MatchGapContainer";

vi.mock("@/lib/runs/sse", () => ({ watchRun: vi.fn(() => vi.fn()) }));

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
    {
      key: "kubernetes",
      skill: "Kubernetes",
      themeId: "infra",
      covered: false,
      members: { Kubernetes: 2 },
      must: 1,
      nice: 0,
      tech: 1,
      jobCount: 2,
    },
    {
      key: "terraform",
      skill: "Terraform",
      themeId: "infra",
      covered: true,
      members: { Terraform: 1 },
      must: 1,
      nice: 0,
      tech: 0,
      jobCount: 1,
    },
  ],
  edges: [
    { jobId: 1, skill: "Kubernetes", skillKey: "kubernetes", source: "must" },
    { jobId: 2, skill: "Kubernetes", skillKey: "kubernetes", source: "tech" },
    { jobId: 2, skill: "Terraform", skillKey: "terraform", source: "must" },
  ],
  themes: [
    {
      id: "infra",
      label: "Cloud / Infrastructure",
      essentialScore: 7,
      popularScore: 3,
      jobCount: 2,
      skillCount: 2,
      gapCount: 1,
    },
  ],
  suggestionStatuses: [
    { kind: "skill", key: "terraform", state: "ready", generatedAt: "2026-06-27T12:00:00Z" },
  ],
};

describe("MatchGapContainer", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps selection while switching between the controlled map and outline", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json(populated)));
    wrap(<MatchGapContainer />);

    expect(await screen.findByText("Skill constellation")).toBeInTheDocument();
    expect(screen.getAllByText("2", { selector: "div.text-3xl" })).toHaveLength(2);
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Cloud / Infrastructure" }));
    expect(screen.getByRole("button", { name: "Open selection tray" })).toHaveTextContent("1");

    await userEvent.click(screen.getByRole("tab", { name: "Outline" }));
    expect(screen.getByText("Ranked skill themes")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Cloud / Infrastructure theme" })).toBeChecked();

    await userEvent.click(screen.getByRole("tab", { name: "Map" }));
    expect(screen.getByRole("checkbox", { name: "Select Cloud / Infrastructure" })).toBeChecked();
  });

  it("focuses one theme and hides unrelated branches until returning to the overview", async () => {
    const backendSkill = {
      key: "python",
      skill: "Python",
      themeId: "backend",
      covered: true,
      members: { Python: 1 },
      must: 1,
      nice: 0,
      tech: 0,
      jobCount: 1,
    };
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({
          ...populated,
          skills: [...populated.skills, backendSkill],
          edges: [
            ...populated.edges,
            { jobId: 1, skill: "Python", skillKey: "python", source: "must" },
          ],
          themes: [
            ...populated.themes,
            {
              id: "backend",
              label: "Backend systems",
              essentialScore: 3,
              popularScore: 1,
              jobCount: 1,
              skillCount: 1,
              gapCount: 0,
            },
          ],
        }),
      ),
    );
    wrap(<MatchGapContainer />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Focus Cloud / Infrastructure" }),
    );
    expect(screen.queryByRole("button", { name: "Focus Backend systems" })).not.toBeInTheDocument();
    expect(screen.getByText(/showing 2 connected skills/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^All themes$/ }));
    expect(screen.getByRole("button", { name: "Focus Backend systems" })).toBeInTheDocument();
  });

  it("shows accessible no-jobs and request-error states", async () => {
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({ ...populated, targetTotal: 0, jobs: [], skills: [], edges: [], themes: [], suggestionStatuses: [] }),
      ),
    );
    const first = wrap(<MatchGapContainer />);
    expect(await screen.findByText(/no target jobs yet/i)).toBeInTheDocument();
    first.unmount();

    server.use(http.get("/api/match-gap", () => HttpResponse.json({}, { status: 500 })));
    wrap(<MatchGapContainer />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't load skill demand/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("has no axe violations when populated", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json(populated)));
    const { container } = wrap(<MatchGapContainer />);
    await screen.findByText("Skill constellation");

    expect((await axe(container)).violations).toEqual([]);
  });
});
