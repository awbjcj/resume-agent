import type { CategoryRow, SkillRow } from "./aggregate";

export type MapView =
  | { level: "galaxy" }
  | { level: "category"; slug: string }
  | { level: "domain"; domainId: string; categorySlug: string };

export interface MapNode {
  id: string;
  entityKey: string;
  kind: "category" | "domain" | "skill";
  label: string;
  radius: number;
  width: number;
  height: number;
  score: number;
  categoryKind?: "hard" | "soft";
  gapCount?: number;
  covered?: boolean;
  coverage?: SkillRow["coverage"];
  domainId?: string;
  skill?: SkillRow;
  x: number;
  y: number;
}

export interface MapLink { source: string; target: string }

const HORIZONTAL_PADDING = 40;
const VERTICAL_PADDING = 48;
// Horizontal breathing room reserved between adjacent nodes in the overview
// grid. Kept wide enough that a node's floating menu and its "N gaps" label
// never reach into the neighbouring column.
const NODE_GAP = 56;
// Vertical stride per node in a focused column. Must clear the tallest pill
// plus the meta label row beneath it so labels are never covered by the next
// node down.
const ROW_HEIGHT = 92;

function nodeRadius(score: number, kind: MapNode["kind"]): number {
  const base = kind === "category" ? 20 : kind === "domain" ? 18 : 12;
  const limit = kind === "category" ? 42 : kind === "domain" ? 38 : 28;
  return Math.min(limit, base + Math.sqrt(Math.max(0, score)) * 3);
}

function createNode(value: Omit<MapNode, "width" | "height" | "x" | "y">): MapNode {
  const width = Math.min(238, Math.max(value.radius * 2, 66 + value.label.length * 6.8));
  return { ...value, width, height: 62, x: 0, y: 0 };
}

function categoryNode(category: CategoryRow): MapNode {
  return createNode({ id: `category:${category.slug}`, entityKey: category.slug, kind: "category", label: category.label, radius: nodeRadius(category.score, "category"), score: category.score, categoryKind: category.kind, gapCount: category.gapCount });
}

export function buildGraph(categoryRows: CategoryRow[], view: MapView): { nodes: MapNode[]; links: MapLink[]; rootId: string | null } {
  const galaxy = () => ({ nodes: categoryRows.map(categoryNode), links: [], rootId: null });
  if (view.level === "galaxy") return galaxy();
  const category = categoryRows.find((row) => row.slug === (view.level === "category" ? view.slug : view.categorySlug));
  if (!category) return galaxy();
  if (view.level === "category") {
    const root = categoryNode(category);
    const leaves = category.domains.map((domain) => createNode({ id: `domain:${domain.id}`, entityKey: domain.id, kind: "domain", label: domain.label, radius: nodeRadius(domain.score, "domain"), score: domain.score, gapCount: domain.gapCount, domainId: domain.id }));
    return { nodes: [root, ...leaves], links: leaves.map((node) => ({ source: root.id, target: node.id })), rootId: root.id };
  }
  const domain = category.domains.find((row) => row.id === view.domainId);
  if (!domain) return galaxy();
  const root = createNode({ id: `domain:${domain.id}`, entityKey: domain.id, kind: "domain", label: domain.label, radius: nodeRadius(domain.score, "domain"), score: domain.score, gapCount: domain.gapCount, domainId: domain.id });
  const leaves = domain.skills.map((skill) => createNode({ id: `skill:${skill.key}`, entityKey: skill.key, kind: "skill", label: skill.skill, radius: nodeRadius(skill.score, "skill"), score: skill.score, covered: skill.covered, coverage: skill.coverage, domainId: domain.id, skill }));
  return { nodes: [root, ...leaves], links: leaves.map((node) => ({ source: root.id, target: node.id })), rootId: root.id };
}

export function parentView(view: MapView): MapView | null {
  if (view.level === "galaxy") return null;
  return view.level === "category" ? { level: "galaxy" } : { level: "category", slug: view.categorySlug };
}

export function drillTarget(view: MapView, node: MapNode): MapView {
  const rootId = view.level === "category" ? `category:${view.slug}` : view.level === "domain" ? `domain:${view.domainId}` : null;
  if (node.id === rootId) return parentView(view) ?? view;
  if (view.level === "galaxy" && node.kind === "category") return { level: "category", slug: node.entityKey };
  if (view.level === "category" && node.kind === "domain") return { level: "domain", domainId: node.entityKey, categorySlug: view.slug };
  return view;
}

function overviewColumns(nodes: MapNode[], width: number): number {
  const widest = Math.max(160, ...nodes.map((node) => node.width));
  return Math.max(1, Math.min(nodes.length, Math.floor((width - HORIZONTAL_PADDING * 2 + NODE_GAP) / (widest + NODE_GAP))));
}

export function recommendedLayoutHeight(nodes: MapNode[], width: number): number {
  const leaves = Math.max(0, nodes.length - (nodes.some((node) => node.kind === "category" && nodes.length > 1) || nodes.some((node) => node.kind === "skill") ? 1 : 0));
  if (nodes.some((node) => node.kind === "skill") || nodes.some((node) => node.kind === "domain") && nodes.some((node) => node.kind === "category")) {
    if (width < 480) return Math.max(520, 164 + leaves * ROW_HEIGHT);
    return Math.max(width < 760 ? 560 : 540, 180 + Math.ceil(leaves / 2) * ROW_HEIGHT);
  }
  return Math.max(width < 640 ? 460 : 500, 108 + Math.ceil(nodes.length / overviewColumns(nodes, width)) * 104);
}

function spreadVertically(nodes: MapNode[], x: number, height: number): MapNode[] {
  const step = (height - VERTICAL_PADDING * 2) / Math.max(1, nodes.length);
  return nodes.map((node, index) => ({ ...node, x, y: VERTICAL_PADDING + step * (index + 0.5) }));
}

function layoutFocused(nodes: MapNode[], width: number, height: number, rootId: string): MapNode[] {
  const root = nodes.find((node) => node.id === rootId);
  const leaves = nodes.filter((node) => node.id !== rootId);
  if (!root) return [];
  if (leaves.length === 0) return [{ ...root, x: width / 2, y: height / 2 }];
  if (leaves.length === 1) return [{ ...root, x: width / 2, y: height * 0.32 }, { ...leaves[0], x: width / 2, y: height * 0.68 }];
  if (width < 480) return [{ ...root, x: width / 2, y: 68 }, ...leaves.map((node, index) => ({ ...node, x: width / 2, y: 164 + index * ROW_HEIGHT }))];
  const left = leaves.filter((_, index) => index % 2 === 0);
  const right = leaves.filter((_, index) => index % 2 === 1);
  if (width < 760) return [{ ...root, x: width / 2, y: 76 }, ...spreadVertically(left, Math.max(128, width * 0.24), height), ...spreadVertically(right, Math.min(width - 128, width * 0.76), height)];
  return [{ ...root, x: width / 2, y: height / 2 }, ...spreadVertically(left, Math.max(136, width * 0.16), height), ...spreadVertically(right, Math.min(width - 136, width * 0.84), height)];
}

function layoutOverview(nodes: MapNode[], width: number, height: number): MapNode[] {
  const columns = overviewColumns(nodes, width);
  const rows = Math.ceil(nodes.length / columns);
  const cellWidth = (width - HORIZONTAL_PADDING * 2) / columns;
  const cellHeight = (height - VERTICAL_PADDING * 2) / Math.max(1, rows);
  return nodes.map((node, index) => { const row = Math.floor(index / columns); const count = Math.min(columns, nodes.length - row * columns); const column = index - row * columns; return { ...node, x: (width - cellWidth * count) / 2 + cellWidth * (column + 0.5), y: VERTICAL_PADDING + cellHeight * (row + 0.5) }; });
}

export function runLayout(inputNodes: MapNode[], _links: MapLink[], width: number, height: number, rootId: string | null): MapNode[] {
  const nodes = [...inputNodes].sort((left, right) => left.id.localeCompare(right.id));
  return rootId ? layoutFocused(nodes, width, height, rootId) : layoutOverview(nodes, width, height);
}
