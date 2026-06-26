import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { industryLabel } from "@/lib/filters/sic-labels";
import type { FilterState } from "@/lib/filters/types";

const SET_KEYS: (keyof FilterState)[] = [
  "source",
  "status",
  "remote",
  "sponsorship",
  "seniority",
  "employmentType",
  "industry",
  "country",
  "region",
  "city",
  "companySize",
  "skills",
];

export function ActiveFilterSummary({
  filter,
  total,
  onRemove,
  onClear,
}: {
  filter: FilterState;
  total: number;
  onRemove: (key: keyof FilterState, value: string) => void;
  onClear: () => void;
}) {
  // Chips key removal off the raw wire value, but show a resolved label
  // (industry SIC codes → names; underscores → spaces for the rest).
  const chips: { key: keyof FilterState; value: string; label: string }[] = [];
  for (const key of SET_KEYS) {
    for (const value of filter[key] as Set<string>) {
      const label = key === "industry" ? industryLabel(value) : value.replace(/_/g, " ");
      chips.push({ key, value, label });
    }
  }

  const scalars: { key: keyof FilterState; value: string; label: string }[] = [];
  const scalar = (key: keyof FilterState, value: string) =>
    scalars.push({ key, value, label: value });
  if (filter.q.trim()) scalar("q", `Search: ${filter.q.trim()}`);
  if (filter.fitMin != null) scalar("fitMin", `Fit >= ${filter.fitMin}`);
  if (filter.maxFit != null) scalar("maxFit", `Fit <= ${filter.maxFit}`);
  if (filter.salaryMin != null) scalar("salaryMin", `Salary >= ${filter.salaryMin}`);
  if (filter.staleDays != null) scalar("staleDays", `Stale > ${filter.staleDays}d`);

  if (!chips.length && !scalars.length) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        Active
      </span>
      {[...chips, ...scalars].map(({ key, value, label }) => (
        <Button
          key={`${key}:${value}`}
          size="sm"
          variant="secondary"
          className="h-7 rounded-full px-2.5 text-xs"
          onClick={() => onRemove(key, value)}
        >
          {label}
          <XIcon data-icon="inline-end" />
        </Button>
      ))}
      <span className="ml-auto text-xs text-muted-foreground">
        {total.toLocaleString()} matching
        <Button variant="link" size="sm" className="h-auto px-2 py-0" onClick={onClear}>
          Clear all
        </Button>
      </span>
    </div>
  );
}
