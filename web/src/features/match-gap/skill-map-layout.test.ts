import { expect, it } from "vitest";

import type { ThemeRow } from "./aggregate";
import { buildGraph, nextExpandedThemes, runLayout } from "./skill-map-layout";

const themes: ThemeRow[] = [
  {
    id: "backend",
    label: "Backend",
    score: 16,
    jobCount: 3,
    skillCount: 1,
    gapCount: 1,
    skills: [
      {
        key: "python",
        skill: "Python",
        themeId: "backend",
        covered: false,
        score: 9,
        jobCount: 3,
        must: 3,
        nice: 0,
        tech: 0,
        members: {},
      },
    ],
  },
  {
    id: "cloud",
    label: "Cloud",
    score: 4,
    jobCount: 1,
    skillCount: 0,
    gapCount: 0,
    skills: [],
  },
];

it("builds prefixed hubs and only expanded skill leaves", () => {
  const collapsed = buildGraph(themes, []);
  const expanded = buildGraph(themes, ["backend"]);

  expect(collapsed.nodes.map((node) => node.id)).toEqual([
    "theme:backend",
    "theme:cloud",
  ]);
  expect(expanded.nodes.map((node) => node.id)).toContain("skill:python");
  expect(expanded.links).toContainEqual({
    source: "theme:backend",
    target: "skill:python",
  });
});

it("keeps only the two most recently expanded themes", () => {
  expect(nextExpandedThemes(["one", "two"], "three")).toEqual(["two", "three"]);
  expect(nextExpandedThemes(["one", "two"], "two")).toEqual(["one"]);
});

it("lays out cloned inputs deterministically without mutating links", () => {
  const graph = buildGraph(themes, ["backend"]);
  const linksBefore = structuredClone(graph.links);
  const forward = runLayout(graph.nodes, graph.links, 800, 500);
  const reverse = runLayout([...graph.nodes].reverse(), graph.links, 800, 500);

  expect(graph.links).toEqual(linksBefore);
  expect(forward.map(({ id, x, y }) => [id, Math.round(x), Math.round(y)]).sort()).toEqual(
    reverse.map(({ id, x, y }) => [id, Math.round(x), Math.round(y)]).sort(),
  );
  expect(forward.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y))).toBe(
    true,
  );
});
