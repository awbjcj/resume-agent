import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { FitMeter } from "@/components/FitMeter";
import { StatusBadge } from "@/components/StatusBadge";
import { locationLabel } from "@/lib/format";
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
    <Card className="min-w-0 flex items-start gap-3 p-4 transition-[box-shadow,transform] duration-200 ease-out-strong hover:-translate-y-0.5 hover:shadow-card-raised hover:ring-primary/40 motion-reduce:hover:translate-y-0 sm:gap-4 sm:p-5">
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
        <div className="break-words text-base font-semibold leading-snug group-hover:text-primary sm:text-lg">
          {row.title ?? "—"}
        </div>
        <div className="mt-1 text-sm text-muted-foreground">
          {row.company ?? "—"} · {locationLabel(row) ?? "location n/a"}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <StatusBadge status={row.status} />
          <span className="text-xs font-medium text-muted-foreground">{row.source}</span>
        </div>
        {(row.status === "rejected" || row.status === "filtered") && row.rejectReason && (
          <span className="mt-2.5 block text-sm leading-snug text-rose-700 dark:text-rose-300">
            <span className="font-medium">
              {row.status === "filtered" || row.rejectCategory === "filtered"
                ? "Filtered out:"
                : "Rejected:"}
            </span>{" "}
            {row.rejectReason}
          </span>
        )}
      </button>
      <FitMeter score={row.fitScore} />
    </Card>
  );
}
