import { Bar, BarChart, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { components } from "@/lib/api/schema";

type Cohort = components["schemas"]["CohortOut"];

// The three series are funnel depth, so they ramp rather than pick arbitrary
// hues: pale at the wide top, saturated brand teal in the middle, green at the
// rare successful end. The previous mapping drew them from *text* colors
// (`--muted-foreground`, `--foreground`), which made the volume series read as
// disabled and the offers series as body copy — and left the purpose-built
// `--chart-*` ramp, which is already tuned for both themes, entirely unused.
const config: ChartConfig = {
  applications: { label: "Apps", color: "var(--chart-4)" },
  interviews: { label: "Interviews", color: "var(--chart-1)" },
  offers: { label: "Offers", color: "var(--chart-2)" },
};

export function ConversionChart({ rows }: { rows: Cohort[] }) {
  // Visual enhancement only; the cohort table is the canonical accessible form.
  return (
    <div
      aria-hidden="true"
      className="rounded-lg border bg-card p-5 shadow-card"
    >
      <div className="mb-4">
        <div className="text-sm font-semibold">Conversion shape</div>
        <div className="text-xs text-muted-foreground">Applications, interviews, and offers.</div>
      </div>
      <ChartContainer config={config} className="h-72 w-full">
        <BarChart data={rows} accessibilityLayer>
          <XAxis dataKey="label" tickLine={false} axisLine={false} />
          <YAxis allowDecimals={false} width={28} />
          <ChartTooltip content={<ChartTooltipContent />} />
          {/* Three unlabelled bars per group were unreadable without hovering;
              the legend names the series up front. */}
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="applications" fill="var(--color-applications)" radius={4} />
          <Bar dataKey="interviews" fill="var(--color-interviews)" radius={4} />
          <Bar dataKey="offers" fill="var(--color-offers)" radius={4} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}
