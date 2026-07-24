import { Fragment } from "react";

import { recency, salaryLabel } from "@/lib/format";

type ShortlistDetailsRow = {
  salaryMin?: number | null;
  salaryMax?: number | null;
  salaryCurrency?: string | null;
  industry?: string | null;
  postedAt?: string | null;
};

export function ShortlistDetails({ row }: { row: ShortlistDetailsRow }) {
  const details = [
    {
      label: "Compensation",
      value: salaryLabel(row.salaryMin, row.salaryMax, row.salaryCurrency),
      className: "font-medium text-emerald-700 dark:text-emerald-300",
    },
    {
      label: "Industry",
      value: row.industry,
      className: "text-primary",
    },
    {
      label: "Posted",
      value: recency(row.postedAt),
      className: "text-muted-foreground",
    },
  ].filter((detail) => Boolean(detail.value));

  if (!details.length) return null;

  return (
    <div
      className="flex min-w-0 items-baseline gap-2 overflow-hidden whitespace-nowrap"
      aria-label="Job details"
    >
      {details.map((detail, index) => (
        <Fragment key={detail.label}>
          {index > 0 && (
            <span aria-hidden className="shrink-0 text-border">
              •
            </span>
          )}
          <span
            className={`min-w-0 truncate text-sm ${detail.className}`}
            title={`${detail.label}: ${detail.value}`}
          >
            <span className="sr-only">{detail.label}: </span>
            {detail.value}
          </span>
        </Fragment>
      ))}
    </div>
  );
}
