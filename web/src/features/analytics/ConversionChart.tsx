import { Bar, BarChart, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { components } from "@/lib/api/schema";

type Cohort = components["schemas"]["CohortOut"];

const config: ChartConfig = {
  applications: { label: "Apps", color: "var(--muted-foreground)" },
  interviews: { label: "Interviews", color: "var(--primary)" },
  offers: { label: "Offers", color: "var(--foreground)" },
};

export function ConversionChart({ rows }: { rows: Cohort[] }) {
  // Visual enhancement only; the cohort table is the canonical accessible form.
  return (
    <div aria-hidden="true">
      <ChartContainer config={config} className="h-56 w-full">
        <BarChart data={rows} accessibilityLayer>
          <XAxis dataKey="label" tickLine={false} axisLine={false} />
          <YAxis allowDecimals={false} width={28} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Bar dataKey="applications" fill="var(--color-applications)" radius={4} />
          <Bar dataKey="interviews" fill="var(--color-interviews)" radius={4} />
          <Bar dataKey="offers" fill="var(--color-offers)" radius={4} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}
