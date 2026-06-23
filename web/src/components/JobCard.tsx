import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { FitMeter } from "./FitMeter";
import { metaLine } from "@/lib/format";
import type { ShortlistItem } from "@/lib/filters/types";

const SPONSORSHIP_PILL: Record<string, string> = {
  offered:
    "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  denied:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
};

const SKILL_CAP = 7;

export function JobCard({
  row,
  activeSkills,
  onOpen,
  footer,
}: {
  row: ShortlistItem;
  activeSkills: Set<string>;
  onOpen: () => void;
  footer?: ReactNode;
}) {
  // Must-have first, then best-have — same priority the modal groups by.
  const sorted = [...row.skills].sort(
    (a, b) => Number(b.required) - Number(a.required),
  );
  const shown = sorted.slice(0, SKILL_CAP);
  const overflow = sorted.length - shown.length;
  const meta = metaLine(row);
  const sponsorPill =
    row.sponsorshipSignal && SPONSORSHIP_PILL[row.sponsorshipSignal];

  return (
    <Card className="flex min-h-[280px] flex-col gap-4 p-5 transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_16px_40px_rgba(24,32,38,0.08)]">
      <button
        type="button"
        onClick={onOpen}
        className="group flex flex-1 gap-4 rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <FitMeter score={row.fitScore} />
        <div className="min-w-0 flex-1">
          <div className="text-xl font-semibold leading-snug group-hover:text-primary">
            {row.title ?? "—"}
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            {row.company ?? "—"} · {row.location ?? "location n/a"}
          </div>

          {(meta.length > 0 || sponsorPill) && (
            <div className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
              {meta.map((part, i) => (
                <span key={part} className="flex items-center gap-1.5">
                  {i > 0 && <span aria-hidden className="opacity-40">·</span>}
                  {part}
                </span>
              ))}
              {sponsorPill && (
                <span
                  className={`ml-1 rounded-full border px-2 py-0.5 text-[0.66rem] font-semibold uppercase tracking-wide ${sponsorPill}`}
                >
                  {row.sponsorshipSignal === "offered" ? "sponsors" : "no sponsor"}
                </span>
              )}
            </div>
          )}

          {sorted.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              {shown.map((t) => (
                <span
                  key={t.name}
                  className="skill-chip"
                  data-covered={t.covered}
                  data-active={activeSkills.has(t.name.toLowerCase())}
                >
                  {!t.required && <span aria-hidden className="opacity-50">+</span>}
                  {t.name}
                </span>
              ))}
              {overflow > 0 && (
                <span className="text-xs font-medium text-muted-foreground">
                  +{overflow} more
                </span>
              )}
            </div>
          )}

          {row.fitRationale && (
            <p className="mt-4 line-clamp-4 text-sm leading-6 text-muted-foreground">
              {row.fitRationale}
            </p>
          )}
        </div>
      </button>
      {footer && <div className="mt-auto border-t pt-4">{footer}</div>}
    </Card>
  );
}
