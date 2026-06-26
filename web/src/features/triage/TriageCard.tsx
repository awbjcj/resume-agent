import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { FitMeter } from "@/components/FitMeter";
import { StatusBadge } from "@/components/StatusBadge";
import type { TriageItem } from "./use-triage";

export function TriageCard({
  row,
  checked,
  onCheck,
  onOpen,
}: {
  row: TriageItem;
  checked: boolean;
  onCheck: (v: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <Card className="min-w-0 flex items-start gap-4 p-5 transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_16px_40px_rgba(24,32,38,0.08)]">
      <div className="pt-1">
        <Checkbox
          checked={checked}
          onCheckedChange={(v) => onCheck(!!v)}
          aria-label={`Select job ${row.jobId}`}
        />
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="group min-w-0 flex-1 rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <div className="break-words text-lg font-semibold leading-snug group-hover:text-primary">
          {row.title ?? "—"}
        </div>
        <div className="mt-1 text-sm text-muted-foreground">
          {row.company ?? "—"} · {row.location ?? "location n/a"}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <StatusBadge status={row.status} />
          <span className="text-xs font-medium text-muted-foreground">{row.source}</span>
        </div>
      </button>
      <FitMeter score={row.fitScore} />
    </Card>
  );
}
