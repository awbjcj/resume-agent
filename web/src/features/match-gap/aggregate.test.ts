import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";
import {
  deriveView,
  sortSkillsWithin,
  targetId,
  type Filters,
  type SkillRow,
} from "./aggregate";

type Payload = components["schemas"]["MatchGapOut"];

const base: Filters = {
  q: "",
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
    {
      key: "kubernetes",
      skill: "Kubernetes",
      themeId: "infra",
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
      themeId: "language",
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
  themes: [
    {
      id: "infra",
      label: "Cloud / Infrastructure",
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

  it("recomputes theme scores and matching jobs after filtering", () => {
    const view = deriveView(payload, { ...base, company: "Datadog" });

    expect(view.filteredJobCount).toBe(1);
    expect(view.themeRows).toEqual([
      expect.objectContaining({ id: "infra", score: 1, jobCount: 1, gapCount: 1 }),
    ]);
  });

  it("recomputes themes after gaps-only removes covered skills", () => {
    const view = deriveView(payload, { ...base, gapsOnly: true });

    expect(view.skills.map((skill) => skill.key)).toEqual(["kubernetes"]);
    expect(view.themeRows.map((theme) => theme.id)).toEqual(["infra"]);
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
    expect(all.themeRows.find((theme) => theme.id === "infra")).toEqual(
      expect.objectContaining({ gapCount: 0, adjacentCount: 1 }),
    );
    expect(gapsOnly.skills).toEqual([]);
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
  themeId: "theme",
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
    targetId({ kind: "theme", key: "skill:c:sharp" }),
  );
});
