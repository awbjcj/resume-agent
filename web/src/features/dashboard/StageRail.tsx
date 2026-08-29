import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";

import type { DashboardSummary } from "./use-dashboard-summary";

type Stage = {
  key: string;
  label: string;
  labelKey: `dashboard.stages.${"raw" | "triage" | "shortlist" | "approved" | "tailored" | "rendered" | "applied"}`;
  count: (s: DashboardSummary) => number;
};

const status = (key: string) => (s: DashboardSummary) =>
  s.statusCounts[key] ?? 0;

export const RAIL_STAGES: Stage[] = [
  {
    key: "raw",
    label: "Raw",
    labelKey: "dashboard.stages.raw",
    count: (s) => (s.statusCounts.raw ?? 0) + (s.statusCounts.extracted ?? 0),
  },
  { key: "triage", label: "Triage", labelKey: "dashboard.stages.triage", count: status("filtered") },
  { key: "shortlist", label: "Shortlist", labelKey: "dashboard.stages.shortlist", count: status("shortlisted") },
  { key: "approved", label: "Approved", labelKey: "dashboard.stages.approved", count: status("approved") },
  { key: "tailored", label: "Tailored", labelKey: "dashboard.stages.tailored", count: status("tailored") },
  { key: "rendered", label: "Rendered", labelKey: "dashboard.stages.rendered", count: status("rendered") },
  { key: "applied", label: "Applied", labelKey: "dashboard.stages.applied", count: (s) => s.applied },
];

export function StageRail({ summary }: { summary: DashboardSummary }) {
  const { t } = useTranslation();
  return (
    <ol
      aria-label={t("dashboard.pipelineStages")}
      className="flex flex-wrap items-center gap-x-1 gap-y-4 rounded-lg border bg-card px-4 py-4 shadow-card"
    >
      {RAIL_STAGES.map((stage, index) => {
        const count = stage.count(summary);
        const empty = count === 0;
        return (
          // Stages size to their own label; only the ones carrying a connector
          // grow, so the row's slack lands in the connector and never squeezes
          // the label. Equal `flex-1` slots looked tidy in code but were
          // narrower than the tracked uppercase text, ellipsizing five of seven
          // labels to "SHORT…" — a stage name is wayfinding, never truncatable.
          <li
            key={stage.key}
            className={cn("flex items-center", index > 0 && "grow")}
          >
            {index > 0 && (
              // Fades along the flow direction so the rail reads left-to-right
              // as a funnel rather than as seven equally-weighted chips.
              //
              // The basis is deliberately tiny and the width comes entirely
              // from `grow`: a wrapping flex container decides line breaks from
              // each item's basis *before* it shrinks anything, so a connector
              // with a real width (w-10) pushed the last stage onto its own row
              // instead of compressing.
              <span
                aria-hidden="true"
                className="mx-2 h-px w-2 grow bg-gradient-to-r from-transparent to-border"
              />
            )}
            <div className="shrink-0">
              <div
                className={cn(
                  "text-2xl font-semibold tabular-nums leading-none tracking-[-0.02em]",
                  // Only the count recedes when a stage is empty; the label is
                  // wayfinding and has to stay readable at every state.
                  empty && "text-muted-foreground/45",
                )}
              >
                {count}
              </div>
              <div className="mt-1.5 whitespace-nowrap text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                {t(stage.labelKey)}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
