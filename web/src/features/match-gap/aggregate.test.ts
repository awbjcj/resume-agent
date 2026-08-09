import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";
import {
  defaultTargetStatuses,
  deriveView,
  hasActiveScopeFilters,
  sortSkillsWithin,
  targetId,
  UNASSIGNED_ID,
  visibleUnassignedSkillKeys,
  type Filters,
  type SkillRow,
} from "./aggregate";

type Payload = components["schemas"]["MatchGapOut"];

const base: Filters = {
  q: "",
  company: null,
  seniority: null,
  statuses: defaultTargetStatuses(),
  gapsOnly: false,
  weighting: "essential",
};

const payload: Payload = {
  targetTotal: 2,
  clustersStale: false,
  taxonomyAlgorithmVersion: "embedding-taxonomy-v1",
  taxonomyMaintenanceDue: true,
  unassignedCount: 0,
  taxonomyUndoAvailable: false,
  categories: [
    { slug: "cloud-infrastructure", label: "Cloud & Infrastructure", kind: "hard" },
    { slug: "programming-languages", label: "Programming Languages", kind: "hard" },
    { slug: "other", label: "Other", kind: "soft" },
  ],
  jobs: [
    { id: 1, company: "Stripe", title: "Backend", seniority: "senior", status: "shortlisted" },
    { id: 2, company: "Datadog", title: "Platform", seniority: "mid", status: "tailored" },
  ],
  skills: [
    {
      key: "kubernetes",
      skill: "Kubernetes",
      domainId: "infra",
      covered: false,
      coverage: "gap",
      members: { Kubernetes: 2, K8s: 1 },
      must: 1,
      nice: 0,
      tech: 1,
      jobCount: 2,
    },
    {
      key: "python",
      skill: "Python",
      domainId: "language",
      covered: true,
      coverage: "covered",
      members: { Python: 1 },
      must: 1,
      nice: 0,
      tech: 0,
      jobCount: 1,
    },
  ],
  edges: [
    { jobId: 1, skillKey: "kubernetes", skill: "Kubernetes", source: "must" },
    { jobId: 2, skillKey: "kubernetes", skill: "Kubernetes", source: "tech" },
    { jobId: 1, skillKey: "python", skill: "Python", source: "must" },
  ],
  domains: [
    {
      id: "infra",
      label: "Cloud / Infrastructure",
      category: "cloud-infrastructure",
      essentialScore: 4,
      popularScore: 2,
      jobCount: 2,
      skillCount: 1,
      gapCount: 1,
      adjacentCount: 0,
    },
    {
      id: "language",
      label: "Languages",
      category: "programming-languages",
      essentialScore: 3,
      popularScore: 1,
      jobCount: 1,
      skillCount: 1,
      gapCount: 0,
      adjacentCount: 0,
    },
  ],
  suggestionStatuses: [
    {
      kind: "skill",
      key: "kubernetes",
      state: "ready",
      generatedAt: "2026-06-27T12:00:00Z",
    },
  ],
};

describe("deriveView", () => {
  it("joins edges by stable key and keeps member evidence", () => {
    const view = deriveView(payload, base);
    const kubernetes = view.skills.find((skill) => skill.key === "kubernetes")!;

    expect(kubernetes.score).toBe(4);
    expect(kubernetes.members).toEqual({ Kubernetes: 2, K8s: 1 });
    expect(view.persistedStateOf("skill", "kubernetes")).toBe("ready");
  });

  it("recomputes domain scores and matching jobs after filtering", () => {
    const view = deriveView(payload, { ...base, company: "Datadog" });

    expect(view.filteredJobCount).toBe(1);
    expect(view.domainRows).toEqual([
      expect.objectContaining({ id: "infra", score: 1, jobCount: 1, gapCount: 1 }),
    ]);
  });

  it("recomputes domains after gaps-only removes covered skills", () => {
    const view = deriveView(payload, { ...base, gapsOnly: true });

    expect(view.skills.map((skill) => skill.key)).toEqual(["kubernetes"]);
    expect(view.domainRows.map((domain) => domain.id)).toEqual(["infra"]);
  });

  it("groups domains under payload categories in authored order", () => {
    const view = deriveView(payload, base);

    expect(view.categoryRows.map((category) => category.slug)).toEqual([
      "cloud-infrastructure",
      "programming-languages",
    ]);
    expect(view.categoryRows[0]).toEqual(
      expect.objectContaining({ kind: "hard", gapCount: 1 }),
    );
  });

  it("keeps zero-count added skills visible under other when unassigned", () => {
    const added: Payload = {
      ...payload,
      skills: [
        ...payload.skills,
        {
          key: "graphql",
          skill: "GraphQL",
          domainId: null,
          covered: false,
          coverage: "gap",
          members: {},
          must: 0,
          nice: 0,
          tech: 0,
          jobCount: 0,
        },
      ],
    };
    const view = deriveView(added, base);

    expect(view.skills).toEqual(
      expect.arrayContaining([expect.objectContaining({ key: "graphql", jobCount: 0 })]),
    );
    expect(
      view.categoryRows.find((category) => category.slug === "other")?.domains[0].id,
    ).toBe(UNASSIGNED_ID);
  });

  it("does not count or filter adjacent skills as true gaps", () => {
    const adjacentPayload: Payload = {
      ...payload,
      skills: payload.skills.map((skill) =>
        skill.key === "kubernetes"
          ? { ...skill, coverage: "adjacent" as const, covered: false }
          : skill,
      ),
    };
    const all = deriveView(adjacentPayload, base);
    const gapsOnly = deriveView(adjacentPayload, { ...base, gapsOnly: true });

    expect(all.skills.find((skill) => skill.key === "kubernetes")?.coverage).toBe(
      "adjacent",
    );
    expect(all.domainRows.find((domain) => domain.id === "infra")).toEqual(
      expect.objectContaining({ gapCount: 0, adjacentCount: 1 }),
    );
    expect(gapsOnly.skills).toEqual([]);
  });

  it("narrows to jobs whose status is in the selected stage set", () => {
    const view = deriveView(payload, { ...base, statuses: new Set(["tailored"]) });

    expect(view.filteredJobCount).toBe(1);
    expect(view.jobsForSkill("kubernetes").map((job) => job.company)).toEqual(["Datadog"]);
  });

  it("computes stage counts before the stage filter narrows jobs, but after other filters", () => {
    const allStages = deriveView(payload, base);
    expect(allStages.statusCounts).toEqual({ shortlisted: 1, tailored: 1 });

    const narrowed = deriveView(payload, { ...base, statuses: new Set(["tailored"]) });
    expect(narrowed.statusCounts).toEqual({ shortlisted: 1, tailored: 1 });

    const byCompany = deriveView(payload, { ...base, company: "Datadog" });
    expect(byCompany.statusCounts).toEqual({ tailored: 1 });
  });

  it("returns filtered demanding jobs by stable skill key", () => {
    const jobs = deriveView(payload, { ...base, company: "Datadog" }).jobsForSkill(
      "kubernetes",
    );

    expect(jobs.map((job) => job.company)).toEqual(["Datadog"]);
  });
});

const row = (key: string, score: number): SkillRow => ({
  key,
  skill: key.toUpperCase(),
  domainId: "domain",
  covered: false,
  coverage: "gap",
  score,
  jobCount: 1,
  must: 1,
  nice: 0,
  tech: 0,
  members: {},
});

it("floats only ready skills above demand order", () => {
  const skills = [row("highest", 9), row("running", 8), row("ready", 1)];
  const state = (key: string) =>
    key === "ready" ? "ready" : key === "running" ? "researching" : "none";

  expect(sortSkillsWithin(skills, state).map((skill) => skill.key)).toEqual([
    "ready",
    "highest",
    "running",
  ]);
});

it("encodes typed target identity without delimiter collisions", () => {
  expect(targetId({ kind: "skill", key: "c:sharp" })).not.toBe(
    targetId({ kind: "domain", key: "skill:c:sharp" }),
  );
});

it("uses only visibility filters, never weighting, to scope a regroup", () => {
  expect(hasActiveScopeFilters({ ...base, weighting: "popular" })).toBe(false);
  expect(hasActiveScopeFilters({ ...base, company: "Stripe" })).toBe(true);
  expect(hasActiveScopeFilters({ ...base, statuses: new Set(["tailored"]) })).toBe(true);

  const unassigned: Payload = {
    ...payload,
    skills: [
      ...payload.skills,
      {
        key: "graphql",
        skill: "GraphQL",
        domainId: null,
        covered: false,
        coverage: "gap",
        members: { GraphQL: 1 },
        must: 1,
        nice: 0,
        tech: 0,
        jobCount: 1,
      },
    ],
    edges: [
      ...payload.edges,
      { jobId: 1, skillKey: "graphql", skill: "GraphQL", source: "must" },
    ],
  };

  expect(visibleUnassignedSkillKeys(deriveView(unassigned, base))).toEqual(["graphql"]);
});

it("scopes visible unassigned skills for company, seniority, stage, search, and gaps", () => {
  const scoped: Payload = {
    ...payload,
    skills: [
      ...payload.skills,
      {
        key: "graphql",
        skill: "GraphQL",
        domainId: null,
        covered: false,
        coverage: "gap",
        members: { GraphQL: 1 },
        must: 1,
        nice: 0,
        tech: 0,
        jobCount: 1,
      },
      {
        key: "redis",
        skill: "Redis",
        domainId: null,
        covered: false,
        coverage: "adjacent",
        members: { Redis: 1 },
        must: 0,
        nice: 1,
        tech: 0,
        jobCount: 1,
      },
    ],
    edges: [
      ...payload.edges,
      { jobId: 1, skillKey: "graphql", skill: "GraphQL", source: "must" },
      { jobId: 2, skillKey: "redis", skill: "Redis", source: "nice" },
    ],
  };

  const keys = (filters: Filters) => visibleUnassignedSkillKeys(deriveView(scoped, filters));

  expect(keys({ ...base, company: "Stripe" })).toEqual(["graphql"]);
  expect(keys({ ...base, seniority: "mid" })).toEqual(["redis"]);
  expect(keys({ ...base, statuses: new Set(["tailored"]) })).toEqual(["redis"]);
  expect(keys({ ...base, q: "graph" })).toEqual(["graphql"]);
  expect(keys({ ...base, gapsOnly: true })).toEqual(["graphql"]);
  expect(keys({ ...base, weighting: "popular" })).toEqual(["graphql", "redis"]);
});
