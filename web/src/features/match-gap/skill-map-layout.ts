import type { SkillRow, ThemeRow } from "./aggregate";

export interface MapNode {
  id: string;
  entityKey: string;
  kind: "theme" | "skill";
  label: string;
  radius: number;
  width: number;
  height: number;
  score: number;
  covered?: boolean;
  coverage?: SkillRow["coverage"];
  themeId?: string;
  skill?: SkillRow;
  x: number;
  y: number;
}

export interface MapLink {
  source: string;
  target: string;
}

const HORIZONTAL_PADDING = 24;
const VERTICAL_PADDING = 40;
const NODE_GAP = 28;
const ROW_HEIGHT = 72;

function nodeRadius(score: number, kind: MapNode["kind"]): number {
  const base = kind === "theme" ? 18 : 12;
  return Math.min(kind === "theme" ? 38 : 28, base + Math.sqrt(Math.max(0, score)) * 3);
}

function nodeWidth(label: string, radius: number): number {
  const estimatedButtonWidth = Math.min(200, Math.max(radius * 2, 28 + label.length * 6.8));
  return estimatedButtonWidth + 38;
}

function createNode(
  value: Omit<MapNode, "width" | "height" | "x" | "y">,
): MapNode {
  return {
    ...value,
    width: nodeWidth(value.label, value.radius),
    height: 54,
    x: 0,
    y: 0,
  };
}

export function nextFocusedTheme(current: string | null, themeId: string): string | null {
  return current === themeId ? null : themeId;
}

export function buildGraph(themeRows: ThemeRow[], focusedThemeId: string | null) {
  const orderedThemes = [...themeRows].sort((left, right) => left.id.localeCompare(right.id));
  const visibleThemes = focusedThemeId
    ? orderedThemes.filter((theme) => theme.id === focusedThemeId)
    : orderedThemes;
  const nodes: MapNode[] = [];
  const links: MapLink[] = [];

  for (const theme of visibleThemes) {
    const themeNodeId = `theme:${theme.id}`;
    const radius = nodeRadius(theme.score, "theme");
    nodes.push(
      createNode({
        id: themeNodeId,
        entityKey: theme.id,
        kind: "theme",
        label: theme.label,
        radius,
        score: theme.score,
      }),
    );
    if (theme.id !== focusedThemeId) continue;

    for (const skill of [...theme.skills].sort((left, right) => left.key.localeCompare(right.key))) {
      const skillNodeId = `skill:${skill.key}`;
      const skillRadius = nodeRadius(skill.score, "skill");
      nodes.push(
        createNode({
          id: skillNodeId,
          entityKey: skill.key,
          kind: "skill",
          label: skill.skill,
          radius: skillRadius,
          score: skill.score,
          covered: skill.covered,
          coverage: skill.coverage,
          themeId: theme.id,
          skill,
        }),
      );
      links.push({ source: themeNodeId, target: skillNodeId });
    }
  }
  return { nodes, links };
}

function overviewColumns(nodes: MapNode[], width: number): number {
  const widestNode = Math.max(160, ...nodes.map((node) => node.width));
  return Math.max(
    1,
    Math.min(nodes.length, Math.floor((width - HORIZONTAL_PADDING * 2 + NODE_GAP) / (widestNode + NODE_GAP))),
  );
}

export function recommendedLayoutHeight(nodes: MapNode[], width: number): number {
  const skillCount = nodes.filter((node) => node.kind === "skill").length;
  if (skillCount > 0) {
    if (width < 480) return Math.max(520, 164 + skillCount * ROW_HEIGHT);
    const rows = Math.ceil(skillCount / 2);
    return Math.max(width < 760 ? 560 : 540, 180 + rows * ROW_HEIGHT);
  }
  const rows = Math.ceil(nodes.length / overviewColumns(nodes, width));
  return Math.max(width < 640 ? 460 : 500, 100 + rows * 88);
}

function spreadVertically(nodes: MapNode[], x: number, height: number): MapNode[] {
  const availableHeight = height - VERTICAL_PADDING * 2;
  const step = availableHeight / Math.max(1, nodes.length);
  return nodes.map((node, index) => ({
    ...node,
    x,
    y: VERTICAL_PADDING + step * (index + 0.5),
  }));
}

function layoutFocused(nodes: MapNode[], width: number, height: number): MapNode[] {
  const root = nodes.find((node) => node.kind === "theme");
  const skills = nodes.filter((node) => node.kind === "skill");
  if (!root) return [];
  if (skills.length === 0) return [{ ...root, x: width / 2, y: height / 2 }];
  if (skills.length === 1) {
    return [
      { ...root, x: width / 2, y: height * 0.32 },
      { ...skills[0], x: width / 2, y: height * 0.68 },
    ];
  }

  if (width < 480) {
    return [
      { ...root, x: width / 2, y: 68 },
      ...skills.map((node, index) => ({
        ...node,
        x: width / 2,
        y: 164 + index * ROW_HEIGHT,
      })),
    ];
  }

  if (width < 760) {
    const left = skills.filter((_, index) => index % 2 === 0);
    const right = skills.filter((_, index) => index % 2 === 1);
    const top = 150;
    const branchHeight = height - top - VERTICAL_PADDING;
    const placeBranch = (branch: MapNode[], x: number) => {
      const step = branchHeight / Math.max(1, branch.length);
      return branch.map((node, index) => ({
        ...node,
        x,
        y: top + step * (index + 0.5),
      }));
    };
    return [
      { ...root, x: width / 2, y: 68 },
      ...placeBranch(left, width * 0.25),
      ...placeBranch(right, width * 0.75),
    ];
  }

  const left = skills.filter((_, index) => index % 2 === 0);
  const right = skills.filter((_, index) => index % 2 === 1);
  return [
    { ...root, x: width / 2, y: height / 2 },
    ...spreadVertically(left, Math.max(112, width * 0.17), height),
    ...spreadVertically(right, Math.min(width - 112, width * 0.83), height),
  ];
}

function layoutOverview(nodes: MapNode[], width: number, height: number): MapNode[] {
  const columns = overviewColumns(nodes, width);
  const rows = Math.ceil(nodes.length / columns);
  const cellWidth = (width - HORIZONTAL_PADDING * 2) / columns;
  const cellHeight = (height - VERTICAL_PADDING * 2) / Math.max(1, rows);

  return nodes.map((node, index) => {
    const row = Math.floor(index / columns);
    const itemsInRow = Math.min(columns, nodes.length - row * columns);
    const column = index - row * columns;
    const rowWidth = cellWidth * itemsInRow;
    return {
      ...node,
      x: (width - rowWidth) / 2 + cellWidth * (column + 0.5),
      y: VERTICAL_PADDING + cellHeight * (row + 0.5),
    };
  });
}

export function runLayout(
  inputNodes: MapNode[],
  _inputLinks: MapLink[],
  width: number,
  height: number,
): MapNode[] {
  const nodes = [...inputNodes].sort((left, right) => left.id.localeCompare(right.id));
  return nodes.some((node) => node.kind === "skill")
    ? layoutFocused(nodes, width, height)
    : layoutOverview(nodes, width, height);
}
