import { Link } from "react-router-dom";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { DashboardSummary } from "./use-dashboard-summary";

export const QUEUE_CARDS = [
  { key: "triage", verb: "Triage", sub: "new jobs to sort", to: "/triage" },
  {
    key: "approve",
    verb: "Approve",
    sub: "shortlisted picks",
    to: "/shortlist",
  },
  {
    key: "tailor",
    verb: "Tailor",
    sub: "approved and ready",
    to: "/pipeline?stage=approved",
  },
  {
    key: "apply",
    verb: "Apply",
    sub: "rendered resumes",
    to: "/pipeline?stage=rendered",
  },
] as const;

export function ActionQueue({ summary }: { summary: DashboardSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {QUEUE_CARDS.map((card) => {
        const count = summary.queues[card.key] ?? 0;
        return (
          <Link
            key={card.key}
            to={card.to}
            aria-label={`${card.verb} ${count} ${card.sub}`}
            className="group rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Card
              className={cn(
                "gap-1 p-4 transition-colors group-hover:border-primary/40",
                count === 0 && "opacity-55",
              )}
            >
              <div className="text-3xl font-semibold tabular-nums leading-none">
                {count}
              </div>
              <CardTitle className="text-sm">{card.verb}</CardTitle>
              <CardDescription className="text-xs">{card.sub}</CardDescription>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
