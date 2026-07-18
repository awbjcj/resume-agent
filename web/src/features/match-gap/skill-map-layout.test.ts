import { expect, it } from "vitest";

import type { CategoryRow, DomainRow } from "./aggregate";
import {
  buildGraph,
  drillTarget,
  parentView,
  recommendedLayoutHeight,
  runLayout,
  type MapNode,
} from "./skill-map-layout";

const domains: DomainRow[] = [
  {
    id: "backend",
    label: "Backend",
    category: "engineering",
    score: 16,
    jobCount: 3,
    skillCount: 1,
    gapCount: 1,
    adjacentCount: 0,
    skills: [
      {
        key: "python",
        skill: "Python",
        domainId: "backend",
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
    category: "engineering",
    score: 4,
    jobCount: 1,
    skillCount: 0,
    gapCount: 0,
    adjacentCount: 0,
    skills: [],
  },
];
const categories: CategoryRow[] = [{ slug: "engineering", label: "Engineering", kind: "hard", score: 20, jobCount: 3, skillCount: 1, gapCount: 1, adjacentCount: 0, domains }];

it("builds category, domain, and skill levels", () => {
  const collapsed = buildGraph(categories, { level: "galaxy" });
  const domainLevel = buildGraph(categories, { level: "category", slug: "engineering" });
  const focused = buildGraph(categories, { level: "domain", domainId: "backend", categorySlug: "engineering" });

  expect(collapsed.nodes.map((node) => node.id)).toEqual([
    "category:engineering",
  ]);
  expect(domainLevel.nodes.map((node) => node.id)).toEqual(["category:engineering", "domain:backend", "domain:cloud"]);
  expect(focused.nodes.map((node) => node.id)).toEqual([
    "domain:backend",
    "skill:python",
  ]);
  expect(focused.nodes.map((node) => node.id)).not.toContain("domain:cloud");
  expect(focused.links).toContainEqual({
    source: "domain:backend",
    target: "skill:python",
  });
});

it("drills down and returns to parent views", () => {
  const galaxy = { level: "galaxy" } as const;
  const category = drillTarget(galaxy, buildGraph(categories, galaxy).nodes[0]);
  expect(category).toEqual({ level: "category", slug: "engineering" });
  expect(parentView(category)).toEqual(galaxy);
  expect(buildGraph(categories, { level: "category", slug: "missing" }).nodes[0].kind).toBe("category");
});

it("lays out cloned inputs deterministically without mutating links", () => {
  const graph = buildGraph(categories, { level: "domain", domainId: "backend", categorySlug: "engineering" });
  const linksBefore = structuredClone(graph.links);
  const height = recommendedLayoutHeight(graph.nodes, 800);
  const forward = runLayout(graph.nodes, graph.links, 800, height, graph.rootId);
  const reverse = runLayout([...graph.nodes].reverse(), graph.links, 800, height, graph.rootId);

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
  for (const graph of [buildGraph(categories, { level: "galaxy" }), buildGraph(categories, { level: "domain", domainId: "backend", categorySlug: "engineering" })]) {
    const width = 800;
    const nodes = runLayout(
      graph.nodes,
      graph.links,
      width,
      recommendedLayoutHeight(graph.nodes, width), graph.rootId,
    );
    for (let left = 0; left < nodes.length; left += 1) {
      for (let right = left + 1; right < nodes.length; right += 1) {
        expect(overlaps(nodes[left], nodes[right])).toBe(false);
      }
    }
  }
});
