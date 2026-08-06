// One-click entry point into the archive/delete workflow: pick a staleness
// bucket, and every job matching it (not just the loaded page) is selected
// via the existing "select all matching" scope -- the bulk action bar below
// then does the actual archive/delete.
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

const STALE_QUICK_OPTIONS = [30, 45, 60, 90] as const;

export function StaleQuickFilters({
  value,
  onSelect,
}: {
  value: number | null;
  onSelect: (days: number | null) => void;
}) {
  const active =
    value != null && (STALE_QUICK_OPTIONS as readonly number[]).includes(value)
      ? [String(value)]
      : [];

  return (
    <div
      aria-label="Quick-select stale jobs"
      className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3"
    >
      <span className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        Select stale
      </span>
      <ToggleGroup
        aria-label="Select jobs by posted age"
        value={active}
        onValueChange={(next) => {
          const picked = next.at(-1);
          onSelect(picked ? Number(picked) : null);
        }}
      >
        {STALE_QUICK_OPTIONS.map((days) => (
          <ToggleGroupItem
            key={days}
            value={String(days)}
            aria-label={`Select every job posted more than ${days} days ago`}
          >
            {days}+ days
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <span className="text-xs text-muted-foreground">
        Selects every matching job so you can archive or delete it below.
      </span>
    </div>
  );
}
