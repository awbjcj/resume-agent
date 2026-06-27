import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";
import { deriveView, type Filters } from "./aggregate";

type Payload = components["schemas"]["MatchGapOut"];

const base: Filters = {
  company: null,
  seniority: null,
  gapsOnly: false,
  weighting: "essential",
};

const payload: Payload = {
  targetTotal: 2,
  clustersStale: false,
  jobs: [
    { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
    { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
  ],
  skills: [
    { skill: "Kubernetes", themeId: "infra", covered: false },
    { skill: "Python", themeId: "lang", covered: true },
  ],
  edges: [
    { jobId: 1, skill: "Kubernetes", source: "must" },
    { jobId: 2, skill: "Kubernetes", source: "tech" },
    { jobId: 1, skill: "Python", source: "must" },
  ],
  themes: [
    { id: "infra", label: "Cloud/Infra" },
    { id: "lang", label: "Languages" },
  ],
};

describe("deriveView", () => {
  it("scores essential demand by source weight", () => {
    const view = deriveView(payload, base);
    const kubernetes = view.skills.find((skill) => skill.skill === "Kubernetes")!;

    expect(kubernetes.score).toBe(4);
    expect(kubernetes.jobCount).toBe(2);
    expect(kubernetes.must).toBe(1);
    expect(kubernetes.tech).toBe(1);
  });

  it("scores popular demand by distinct job count", () => {
    const view = deriveView(payload, { ...base, weighting: "popular" });

    expect(view.skills.find((skill) => skill.skill === "Kubernetes")!.score).toBe(2);
    expect(view.skills.find((skill) => skill.skill === "Python")!.score).toBe(1);
  });

  it("hides covered skills when gaps only is enabled", () => {
    const view = deriveView(payload, { ...base, gapsOnly: true });

    expect(view.skills.map((skill) => skill.skill)).toEqual(["Kubernetes"]);
  });

  it("filters by company and recomputes scores", () => {
    const view = deriveView(payload, { ...base, company: "Datadog" });

    expect(view.skills.map((skill) => skill.skill)).toEqual(["Kubernetes"]);
    expect(view.skills[0].score).toBe(1);
  });

  it("sorts skills by descending score", () => {
    expect(deriveView(payload, base).skills[0].skill).toBe("Kubernetes");
  });

  it("returns demanding jobs for a skill", () => {
    const companies = deriveView(payload, base)
      .jobsForSkill("Kubernetes")
      .map((job) => job.company)
      .sort();

    expect(companies).toEqual(["Datadog", "Stripe"]);
  });

  it("returns the demanding job union for a theme", () => {
    const jobs = deriveView(payload, base).jobsForTheme("infra");

    expect(jobs.map((job) => job.id).sort()).toEqual([1, 2]);
  });

  it("carries gap counts into company rollups", () => {
    const stripe = deriveView(payload, base).byCompany.find((row) => row.key === "Stripe")!;

    expect(stripe.gapCount).toBe(1);
  });

  it("recomputes facet scores from each facet's edges", () => {
    const view = deriveView(payload, base);
    const stripe = view.byCompany.find((row) => row.key === "Stripe")!;
    const datadog = view.byCompany.find((row) => row.key === "Datadog")!;

    expect(stripe.topSkills.find((skill) => skill.skill === "Kubernetes")!.score).toBe(3);
    expect(datadog.topSkills.find((skill) => skill.skill === "Kubernetes")!.score).toBe(1);
  });

  it("exposes sorted filter facets", () => {
    const view = deriveView(payload, base);

    expect(view.companies).toEqual(["Datadog", "Stripe"]);
    expect(view.seniorities).toEqual(["mid", "senior"]);
  });
});
