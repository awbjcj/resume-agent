import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { changeLanguage } from "@/i18n";
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
  beforeEach(async () => {
    await changeLanguage("en");
  });

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
    const trigger = screen.getByRole("button", { name: /why this experience was chosen/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("region", { name: "Evidence selection explanation" })).toBeInTheDocument();
    expect(await screen.findByText("Rule-based selection")).toBeInTheDocument();
    expect(screen.getByText("How this version was tailored")).toBeInTheDocument();
    expect(screen.getByText("Experience used — and why")).toBeInTheDocument();
    expect(screen.getByText("What the job asks for")).toBeInTheDocument();
    expect(screen.getByText("Why chosen:")).toBeInTheDocument();
    expect(screen.getByText("Built Python services")).toBeInTheDocument();
    expect(screen.getByText(/Weaker coverage/)).toBeInTheDocument();
    expect(screen.getByText(/1 fact you added after the original evidence plan/)).toBeInTheDocument();
    expect(requested).toHaveBeenCalledTimes(1);
  });

  it("stays absent for legacy portfolio-less versions", () => {
    renderDisclosure(false);
    expect(screen.queryByRole("button", { name: /why this experience was chosen/i })).not.toBeInTheDocument();
  });

  it("localizes the fixed fallback warning without translating its technical cause", async () => {
    await changeLanguage("zh-CN");
    server.use(
      http.get("/api/resume-versions/9/evidence-portfolio", () =>
        HttpResponse.json({
          ...payload,
          warning: "Evidence planner unavailable (planner unavailable); deterministic fallback used.",
        }),
      ),
    );
    const user = userEvent.setup();
    renderDisclosure();

    await user.click(screen.getAllByRole("button")[0]);

    expect(await screen.findByText("证据规划器不可用（规划器不可用）；已使用基于规则的兜底选择。")).toBeInTheDocument();
  });

  it("shows an accessible error without closing the disclosure", async () => {
    server.use(
      http.get("/api/resume-versions/9/evidence-portfolio", () =>
        HttpResponse.json({ error: { code: "FAILED", message: "Portfolio unavailable" } }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderDisclosure();
    await user.click(screen.getByRole("button", { name: /why this experience was chosen/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Portfolio unavailable");
    expect(screen.getByRole("button", { name: /why this experience was chosen/i })).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps dense evidence concise until the user asks for full details", async () => {
    const densePayload = {
      ...payload,
      highlightTerms: Array.from({ length: 7 }, (_, index) => `Skill ${index + 1}`),
      requirements: Array.from({ length: 7 }, (_, index) => ({
        ...payload.requirements[0],
        priority: index + 1,
        text: `Requirement ${index + 1}`,
      })),
      selections: [
        {
          ...payload.selections[0],
          requirementTexts: ["Need 1", "Need 2", "Need 3", "Need 4"],
          selectedFactIds: ["bullet-1", "bullet-2", "bullet-3"],
        },
      ],
      evidenceExcerpts: [
        payload.evidenceExcerpts[0],
        { ...payload.evidenceExcerpts[0], factId: "bullet-2", text: "Led platform migration" },
        { ...payload.evidenceExcerpts[0], factId: "bullet-3", text: "Reduced deployment time" },
      ],
    };
    server.use(
      http.get("/api/resume-versions/9/evidence-portfolio", () =>
        HttpResponse.json(densePayload),
      ),
    );
    const user = userEvent.setup();
    renderDisclosure();

    await user.click(screen.getByRole("button", { name: /why this experience was chosen/i }));

    const showAll = await screen.findByRole("button", { name: "Show full evidence details" });
    expect(showAll).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Requirement 6")).not.toBeInTheDocument();
    expect(screen.queryByText("Reduced deployment time")).not.toBeInTheDocument();
    expect(screen.getAllByText("+2 more").length).toBeGreaterThan(0);

    await user.click(showAll);

    expect(screen.getByText("Requirement 6")).toBeInTheDocument();
    expect(screen.getByText("Reduced deployment time")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show concise evidence" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
