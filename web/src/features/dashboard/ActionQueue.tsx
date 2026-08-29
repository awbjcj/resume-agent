import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { DashboardSummary } from "./use-dashboard-summary";

export const QUEUE_CARDS = [
  { key: "triage", verb: "Triage", verbKey: "dashboard.queue.triage", sub: "new jobs to sort", subKey: "dashboard.queue.triageDetail", to: "/triage" },
  {
    key: "approve",
    verb: "Approve",
    verbKey: "dashboard.queue.approve",
    sub: "shortlisted picks",
    subKey: "dashboard.queue.approveDetail",
    to: "/shortlist",
  },
  {
    key: "tailor",
    verb: "Tailor",
    verbKey: "dashboard.queue.tailor",
    sub: "approved and ready",
    subKey: "dashboard.queue.tailorDetail",
    to: "/pipeline?stage=approved",
  },
  {
    key: "apply",
    verb: "Apply",
    verbKey: "dashboard.queue.apply",
    sub: "rendered resumes",
    subKey: "dashboard.queue.applyDetail",
    to: "/pipeline?stage=rendered",
  },
] as const;

export function ActionQueue({ summary }: { summary: DashboardSummary }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {QUEUE_CARDS.map((card) => {
        const count = summary.queues[card.key] ?? 0;
        const empty = count === 0;
        return (
          <Link
            key={card.key}
            to={card.to}
            aria-label={`${t(card.verbKey)} ${count} ${t(card.subKey)}`}
            className="group rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            data-empty={empty}
          >
            <Card
              className={cn(
                // Only box-shadow and transform animate — never `all`, which
                // would also transition colour and layout properties. Tailwind
                // draws `ring-1` as a box-shadow layer, so this one property
                // covers both the elevation lift and the ring colour change.
                "h-full gap-1 p-4 transition-[box-shadow,transform] duration-200 ease-out-strong",
                // The hover affordance has to ride the ring: Card draws its
                // edge with `ring-1`, so a border-colour change renders nothing.
                "group-hover:shadow-card-raised group-hover:ring-primary/40",
                // Press feedback: instant, subtle, and on the whole tile so the
                // card reads as the thing being pushed.
                "group-active:scale-[0.985] group-active:duration-100",
              )}
            >
              <div
                className={cn(
                  "text-3xl font-semibold tabular-nums leading-none tracking-[-0.02em]",
                  // Dim the numeral, never the label — an idle queue should read
                  // quiet, but "Triage / new jobs to sort" must stay legible.
                  empty && "text-muted-foreground/45",
                )}
              >
                {count}
              </div>
              <CardTitle className="text-sm">{t(card.verbKey)}</CardTitle>
              <CardDescription className="text-xs">{t(card.subKey)}</CardDescription>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
