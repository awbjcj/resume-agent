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
    <Card className="flex items-start gap-3 p-4">
      <Checkbox
        checked={checked}
        onCheckedChange={(v) => onCheck(!!v)}
        aria-label={`Select job ${row.jobId}`}
      />
      <button onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="font-serif text-base font-semibold">{row.title ?? "—"}</div>
        <div className="text-sm text-muted-foreground">
          {row.company ?? "—"} · {row.location ?? "location n/a"}
        </div>
        <div className="mt-1 flex items-center gap-2">
          <StatusBadge status={row.status} />
          <span className="font-mono text-xs text-muted-foreground">{row.source}</span>
        </div>
      </button>
      <FitMeter score={row.fitScore} />
    </Card>
  );
}
