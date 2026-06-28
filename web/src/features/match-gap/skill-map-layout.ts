import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

import type { SkillRow, ThemeRow } from "./aggregate";

export interface MapNode {
  id: string;
  entityKey: string;
  kind: "theme" | "skill";
  label: string;
  radius: number;
  score: number;
  covered?: boolean;
  themeId?: string;
  skill?: SkillRow;
  x: number;
  y: number;
}

export interface MapLink {
  source: string;
  target: string;
}

type WorkingNode = MapNode & SimulationNodeDatum;
type WorkingLink = SimulationLinkDatum<WorkingNode>;

function nodeRadius(score: number, kind: MapNode["kind"]): number {
  const base = kind === "theme" ? 18 : 12;
  return Math.min(kind === "theme" ? 38 : 28, base + Math.sqrt(Math.max(0, score)) * 3);
}

function hash(value: string): number {
  let current = 2166136261;
  for (const character of value) {
    current ^= character.charCodeAt(0);
    current = Math.imul(current, 16777619);
  }
  return current >>> 0;
}

function seededRandom() {
  let seed = 0x2f6e2b1;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
}

export function nextExpandedThemes(current: string[], themeId: string): string[] {
  if (current.includes(themeId)) return current.filter((id) => id !== themeId);
  return [...current.slice(-1), themeId];
}

export function buildGraph(themeRows: ThemeRow[], expanded: string[]) {
  const expandedSet = new Set(expanded);
  const nodes: MapNode[] = [];
  const links: MapLink[] = [];
  for (const theme of [...themeRows].sort((left, right) => left.id.localeCompare(right.id))) {
    const themeNodeId = `theme:${theme.id}`;
    nodes.push({
      id: themeNodeId,
      entityKey: theme.id,
      kind: "theme",
      label: theme.label,
      radius: nodeRadius(theme.score, "theme"),
      score: theme.score,
      x: 0,
      y: 0,
    });
    if (!expandedSet.has(theme.id)) continue;
    for (const skill of [...theme.skills].sort((left, right) => left.key.localeCompare(right.key))) {
      const skillNodeId = `skill:${skill.key}`;
      nodes.push({
        id: skillNodeId,
        entityKey: skill.key,
        kind: "skill",
        label: skill.skill,
        radius: nodeRadius(skill.score, "skill"),
        score: skill.score,
        covered: skill.covered,
        themeId: theme.id,
        skill,
        x: 0,
        y: 0,
      });
      links.push({ source: themeNodeId, target: skillNodeId });
    }
  }
  return { nodes, links };
}

export function runLayout(
  inputNodes: MapNode[],
  inputLinks: MapLink[],
  width: number,
  height: number,
  ticks = 140,
): MapNode[] {
  const nodes: WorkingNode[] = [...inputNodes]
    .sort((left, right) => left.id.localeCompare(right.id))
    .map((node) => {
      const angle = ((hash(node.id) % 360) * Math.PI) / 180;
      const distance = 40 + (hash(`${node.id}:distance`) % 120);
      return {
        ...node,
        x: width / 2 + Math.cos(angle) * distance,
        y: height / 2 + Math.sin(angle) * distance,
        vx: 0,
        vy: 0,
      };
    });
  const links: WorkingLink[] = inputLinks.map((link) => ({ ...link }));
  const simulation = forceSimulation(nodes)
    .randomSource(seededRandom())
    .force(
      "link",
      forceLink<WorkingNode, WorkingLink>(links)
        .id((node) => node.id)
        .distance((link) => {
          const source = link.source as WorkingNode;
          const target = link.target as WorkingNode;
          return source.radius + target.radius + 54;
        })
        .strength(0.8),
    )
    .force("charge", forceManyBody().strength(-260).distanceMax(360))
    .force("collision", forceCollide<WorkingNode>().radius((node) => node.radius + 16))
    .force("center", forceCenter(width / 2, height / 2))
    .stop();

  simulation.tick(ticks);
  return nodes.map((node) => ({
    ...node,
    x: Math.min(width - node.radius - 12, Math.max(node.radius + 12, node.x ?? width / 2)),
    y: Math.min(height - node.radius - 12, Math.max(node.radius + 12, node.y ?? height / 2)),
  }));
}
