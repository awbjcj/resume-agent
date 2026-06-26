import { FilterIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { FilterState } from "@/lib/filters/types";

export function QuickFilters({ onApply }: { onApply: (patch: Partial<FilterState>) => void }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        Quick prune
      </span>
      <Button size="sm" variant="outline" onClick={() => onApply({ maxFit: 40 })}>
        <FilterIcon data-icon="inline-start" /> Low-fit (&lt;40)
      </Button>
      <Button size="sm" variant="outline" onClick={() => onApply({ staleDays: 45 })}>
        <FilterIcon data-icon="inline-start" /> Stale (&gt;45d)
      </Button>
      <Button size="sm" variant="outline" onClick={() => onApply({ status: new Set(["rejected"]) })}>
        <FilterIcon data-icon="inline-start" /> Off-target rejected
      </Button>
    </div>
  );
}
