import { ResponsiveContainer, Sankey, Tooltip, type SankeyLinkProps } from "recharts";
import { useTranslation } from "react-i18next";

import type { components } from "@/lib/api/schema";
import { CHART_COLORS, stageLabel, STAGE_ORDER, tooltipProps } from "./chart-theme";
import { RateLabel } from "./RateLabel";

type Flow = components["schemas"]["FlowEdgeOut"];

export function toSankeyData(flows: Flow[], t?: Parameters<typeof stageLabel>[1]) {
  const stageIndex = new Map<string, number>(STAGE_ORDER.map((kind, index) => [kind, index]));
  const exits = new Set(["rejected", "no_response", "withdrawn"]);
  const safeFlows = flows.filter((flow) => {
    if (exits.has(flow.target)) return stageIndex.has(flow.source);
    const source = stageIndex.get(flow.source);
    const target = stageIndex.get(flow.target);
    return source !== undefined && target !== undefined && target > source;
  });
  const names: string[] = [];
  const index = (kind: string) => {
    let found = names.indexOf(kind);
    if (found === -1) {
      found = names.length;
      names.push(kind);
    }
    return found;
  };
  const totals = new Map<string, number>();
  for (const flow of safeFlows) totals.set(flow.source, (totals.get(flow.source) ?? 0) + flow.count);
  const links = safeFlows.map((flow) => ({
    source: index(flow.source),
    target: index(flow.target),
    value: flow.count,
    count: flow.count,
    total: totals.get(flow.source) ?? 0,
    sourceKind: flow.source,
    targetKind: flow.target,
    color: edgeColor(flow.target),
  }));
  return { nodes: names.map((name) => ({ name: stageLabel(name, t) })), links };
}

function SankeyLink({
  sourceX,
  sourceY,
  sourceControlX,
  targetControlX,
  targetX,
  targetY,
  linkWidth,
  payload,
}: SankeyLinkProps) {
  const color = (payload as { color?: string }).color ?? CHART_COLORS.flow;
  return (
    <path
      d={`M${sourceX},${sourceY}C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}`}
      fill="none"
      stroke={color}
      strokeOpacity={0.55}
      strokeWidth={Math.max(1, linkWidth)}
    />
  );
}

function edgeColor(target: string): string {
  if (target === "rejected") return CHART_COLORS.rejected;
  if (target === "no_response") return CHART_COLORS.noResponse;
  if (target === "withdrawn") return CHART_COLORS.withdrawn;
  return CHART_COLORS.flow;
}

export function StageFlowChart({ flows }: { flows: Flow[] }) {
  const { t } = useTranslation();
  if (flows.length === 0) {
    return <p className="text-sm text-muted-foreground">Not enough history yet — log a few stages to see where applications go.</p>;
  }
  const data = toSankeyData(flows, t);
  if (data.links.length === 0) {
    return <p className="text-sm text-muted-foreground">Not enough forward stage history yet — repeated and out-of-order entries stay in the timeline without distorting this chart.</p>;
  }
  return (
    <div className="space-y-4">
      <div className="h-80 min-w-0" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <Sankey data={data} nodePadding={24} linkCurvature={0.55} link={SankeyLink}>
            <Tooltip {...tooltipProps} />
          </Sankey>
        </ResponsiveContainer>
      </div>
      <div role="group" aria-label="Stage-flow rates" className="grid gap-2 sm:grid-cols-2">
        {data.links.map((link) => (
          <div
            key={`${link.sourceKind}-${link.targetKind}`}
            className="rounded-md border-l-4 bg-muted/25 px-3 py-2 text-sm"
            style={{ borderLeftColor: edgeColor(link.targetKind) }}
          >
            <p className="font-medium">
              {stageLabel(link.sourceKind, t)} → {stageLabel(link.targetKind, t)}
            </p>
            <RateLabel count={link.count} total={link.total} />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Custom events are excluded from stage flow and cycle time.</p>
    </div>
  );
}
