import { expect, it } from "vitest";

import type { ThemeRow } from "./aggregate";
import {
  buildGraph,
  nextFocusedTheme,
  recommendedLayoutHeight,
  runLayout,
  type MapNode,
} from "./skill-map-layout";

const themes: ThemeRow[] = [
  {
    id: "backend",
    label: "Backend",
    score: 16,
    jobCount: 3,
    skillCount: 1,
    gapCount: 1,
    adjacentCount: 0,
    skills: [
      {
        key: "python",
        skill: "Python",
        themeId: "backend",
        covered: false,
        coverage: "gap",
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
    adjacentCount: 0,
    skills: [],
  },
];

it("builds all hubs in overview and isolates a focused theme with its leaves", () => {
  const collapsed = buildGraph(themes, null);
  const focused = buildGraph(themes, "backend");

  expect(collapsed.nodes.map((node) => node.id)).toEqual([
    "theme:backend",
    "theme:cloud",
  ]);
  expect(focused.nodes.map((node) => node.id)).toEqual([
    "theme:backend",
    "skill:python",
  ]);
  expect(focused.nodes.map((node) => node.id)).not.toContain("theme:cloud");
  expect(focused.links).toContainEqual({
    source: "theme:backend",
    target: "skill:python",
  });
});

it("toggles a single focused theme", () => {
  expect(nextFocusedTheme(null, "backend")).toBe("backend");
  expect(nextFocusedTheme("backend", "backend")).toBeNull();
  expect(nextFocusedTheme("backend", "cloud")).toBe("cloud");
});

it("lays out cloned inputs deterministically without mutating links", () => {
  const graph = buildGraph(themes, "backend");
  const linksBefore = structuredClone(graph.links);
  const height = recommendedLayoutHeight(graph.nodes, 800);
  const forward = runLayout(graph.nodes, graph.links, 800, height);
  const reverse = runLayout([...graph.nodes].reverse(), graph.links, 800, height);

  expect(graph.links).toEqual(linksBefore);
  expect(forward.map(({ id, x, y }) => [id, Math.round(x), Math.round(y)]).sort()).toEqual(
    reverse.map(({ id, x, y }) => [id, Math.round(x), Math.round(y)]).sort(),
  );
  expect(forward.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y))).toBe(
    true,
  );
});

function overlaps(left: MapNode, right: MapNode) {
  return (
    Math.abs(left.x - right.x) < (left.width + right.width) / 2 + 12 &&
    Math.abs(left.y - right.y) < (left.height + right.height) / 2 + 12
  );
}

it("keeps the rendered node boxes separated in overview and focus layouts", () => {
  for (const graph of [buildGraph(themes, null), buildGraph(themes, "backend")]) {
    const width = 800;
    const nodes = runLayout(
      graph.nodes,
      graph.links,
      width,
      recommendedLayoutHeight(graph.nodes, width),
    );
    for (let left = 0; left < nodes.length; left += 1) {
      for (let right = left + 1; right < nodes.length; right += 1) {
        expect(overlaps(nodes[left], nodes[right])).toBe(false);
      }
    }
  }
});
