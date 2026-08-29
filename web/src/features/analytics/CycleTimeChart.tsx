import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { components } from "@/lib/api/schema";
import { axisProps, CHART_COLORS, rateConfidence, STAGE_LABELS, STAGE_ORDER, tooltipProps } from "./chart-theme";

type CycleTime = components["schemas"]["CycleTimeOut"];

export function toCycleRows(cycleTimes: CycleTime[]) {
  const order = new Map(STAGE_ORDER.map((kind, index) => [kind, index]));
  return cycleTimes
    .map((item) => ({
      ...item,
      label: `${STAGE_LABELS[item.fromKind] ?? item.fromKind} → ${STAGE_LABELS[item.toKind] ?? item.toKind}`,
      lowConfidence: rateConfidence(item.sampleSize) !== "ok",
    }))
    .sort((left, right) => {
      const fromDelta = (order.get(left.fromKind as (typeof STAGE_ORDER)[number]) ?? Number.MAX_SAFE_INTEGER)
        - (order.get(right.fromKind as (typeof STAGE_ORDER)[number]) ?? Number.MAX_SAFE_INTEGER);
      if (fromDelta !== 0) return fromDelta;
      return (order.get(left.toKind as (typeof STAGE_ORDER)[number]) ?? Number.MAX_SAFE_INTEGER)
        - (order.get(right.toKind as (typeof STAGE_ORDER)[number]) ?? Number.MAX_SAFE_INTEGER);
    });
}

export function CycleTimeChart({ cycleTimes }: { cycleTimes: CycleTime[] }) {
  if (cycleTimes.length === 0) {
    return <p className="text-sm text-muted-foreground">Not enough history yet — consecutive dated stages will appear here.</p>;
  }
  const rows = toCycleRows(cycleTimes);
  return (
    <div className="space-y-3">
      <div className="h-[min(28rem,70vh)] min-h-64 min-w-0" aria-label="Median days between application stages">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ left: 12, right: 24 }}>
            <XAxis type="number" unit="d" {...axisProps} />
            <YAxis type="category" dataKey="label" width={170} {...axisProps} />
            <Tooltip
              {...tooltipProps}
              formatter={(value, _name, item) => [`${Number(value).toFixed(1)} days · n=${item.payload.sampleSize}`, "Median"]}
            />
            <Bar dataKey="medianDays" radius={[0, 5, 5, 0]}>
              {rows.map((row) => (
                <Cell key={row.label} fill={CHART_COLORS.categorical[1]} opacity={row.lowConfidence ? 0.45 : 1} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only">
        {rows.map((row) => <li key={row.label}>{row.label}: median {row.medianDays} days, n={row.sampleSize}</li>)}
      </ul>
    </div>
  );
}
