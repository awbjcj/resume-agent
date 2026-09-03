import { Bar, BarChart, XAxis, YAxis } from "recharts";
import { useTranslation } from "react-i18next";

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
export function ConversionChart({ rows }: { rows: Cohort[] }) {
  const { t } = useTranslation();
  const config: ChartConfig = {
    applications: { label: t("analytics.conversion.applications"), color: "var(--chart-4)" },
    interviews: { label: t("analytics.conversion.interviews"), color: "var(--chart-1)" },
    offers: { label: t("analytics.conversion.offers"), color: "var(--chart-2)" },
  };
  // The cohort table below is the canonical accessible form of this data, so the
  // plot itself is hidden from assistive tech rather than announced as a pile of
  // unlabelled bars. `aria-hidden` used to sit on the whole card, which also
  // swallowed the panel's title and description — text that appears nowhere
  // else, since the table carries its own, different caption. It now covers
  // exactly the redundant part: the drawing.
  return (
    <div className="rounded-lg border bg-card p-5 shadow-card">
      <div className="mb-4">
        <div className="text-sm font-semibold">{t("analytics.conversion.title")}</div>
        <div className="text-xs text-muted-foreground">{t("analytics.conversion.description")}</div>
      </div>
      <ChartContainer aria-hidden="true" config={config} className="h-72 w-full">
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
