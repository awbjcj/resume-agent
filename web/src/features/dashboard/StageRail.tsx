import { cn } from "@/lib/utils";

import type { DashboardSummary } from "./use-dashboard-summary";

type Stage = {
  key: string;
  label: string;
  count: (s: DashboardSummary) => number;
};

const status = (key: string) => (s: DashboardSummary) =>
  s.statusCounts[key] ?? 0;

export const RAIL_STAGES: Stage[] = [
  {
    key: "raw",
    label: "Raw",
    count: (s) => (s.statusCounts.raw ?? 0) + (s.statusCounts.extracted ?? 0),
  },
  { key: "triage", label: "Triage", count: status("filtered") },
  { key: "shortlist", label: "Shortlist", count: status("shortlisted") },
  { key: "approved", label: "Approved", count: status("approved") },
  { key: "tailored", label: "Tailored", count: status("tailored") },
  { key: "rendered", label: "Rendered", count: status("rendered") },
  { key: "applied", label: "Applied", count: (s) => s.applied },
];

export function StageRail({ summary }: { summary: DashboardSummary }) {
  return (
    <ol
      aria-label="Pipeline stages"
      className="flex flex-wrap items-center gap-y-3 rounded-lg border bg-card px-4 py-4 shadow-sm"
    >
      {RAIL_STAGES.map((stage, index) => {
        const count = stage.count(summary);
        return (
          <li key={stage.key} className="flex min-w-0 flex-1 items-center">
            {index > 0 && (
              <span
                aria-hidden="true"
                className="mx-2 h-px w-full max-w-8 shrink bg-border"
              />
            )}
            <div className={cn("min-w-0", count === 0 && "opacity-45")}>
              <div className="text-2xl font-semibold tabular-nums leading-none">
                {count}
              </div>
              <div className="mt-1 truncate text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {stage.label}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
