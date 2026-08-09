import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { EvidencePortfolioDisclosure } from "./EvidencePortfolioDisclosure";

function renderDisclosure(available = true) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <EvidencePortfolioDisclosure versionId={9} available={available} />
    </QueryClientProvider>,
  );
}

const payload = {
  status: "deterministic_fallback",
  warning: "Planner unavailable; deterministic evidence selection was used.",
  requirements: [
    {
      priority: 1,
      text: "Python",
      kind: "skill",
      coverage: "covered",
      core: true,
      rationale: "Direct profile evidence",
      supportingFactIds: ["bullet-1"],
      approvedTerms: ["Python"],
    },
    {
      priority: 2,
      text: "Kubernetes",
      kind: "skill",
      coverage: "gap",
      core: false,
      rationale: "No profile evidence",
      supportingFactIds: [],
      approvedTerms: [],
    },
  ],
  selections: [
    {
      ownerId: "role-1",
      ownerKind: "experience",
      rank: 1,
      selectedFactIds: ["bullet-1"],
      bulletBudget: 1,
      bridge: false,
      rationale: "Strong direct match",
      requirementTexts: ["Python"],
    },
  ],
  selectedSkillFactIds: ["skill-1"],
  sectionOrder: ["experience", "projects"],
  highlightTerms: ["Python"],
  omissions: [{ ownerId: "role-2", ownerKind: "experience", rationale: "Weaker coverage" }],
  evidenceExcerpts: [{ factId: "bullet-1", ownerId: "role-1", ownerKind: "experience", text: "Built Python services" }],
  realizedOutsideFactIds: ["bullet-user"],
};

describe("EvidencePortfolioDisclosure", () => {
  it("fetches lazily and exposes the fallback, coverage, evidence, and omissions", async () => {
    const requested = vi.fn();
    server.use(
      http.get("/api/resume-versions/9/evidence-portfolio", () => {
        requested();
        return HttpResponse.json(payload);
      }),
    );
    const user = userEvent.setup();
    renderDisclosure();

    expect(requested).not.toHaveBeenCalled();
    const trigger = screen.getByRole("button", { name: "Why this evidence?" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("region", { name: "Evidence portfolio explanation" })).toBeInTheDocument();
    expect(await screen.findByText("Deterministic fallback")).toBeInTheDocument();
    expect(screen.getByText("Built Python services")).toBeInTheDocument();
    expect(screen.getByText(/Weaker coverage/)).toBeInTheDocument();
    expect(screen.getByText(/1 user-added profile fact/)).toBeInTheDocument();
    expect(requested).toHaveBeenCalledTimes(1);
  });

  it("stays absent for legacy portfolio-less versions", () => {
    renderDisclosure(false);
    expect(screen.queryByRole("button", { name: "Why this evidence?" })).not.toBeInTheDocument();
  });

  it("shows an accessible error without closing the disclosure", async () => {
    server.use(
      http.get("/api/resume-versions/9/evidence-portfolio", () =>
        HttpResponse.json({ error: { code: "FAILED", message: "Portfolio unavailable" } }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderDisclosure();
    await user.click(screen.getByRole("button", { name: "Why this evidence?" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Portfolio unavailable");
    expect(screen.getByRole("button", { name: "Why this evidence?" })).toHaveAttribute("aria-expanded", "true");
  });
});
