import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import type { PipelineItem } from "./use-pipeline";

export function PipelineCard({ row, onOpen }: { row: PipelineItem; onOpen: () => void }) {
  return (
    <Card className="p-5 transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_16px_40px_rgba(24,32,38,0.08)]">
      <button
        type="button"
        onClick={onOpen}
        className="group w-full rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-lg font-semibold leading-snug group-hover:text-primary">
              {row.title ?? "—"}
            </div>
            <div className="mt-1 text-sm text-muted-foreground">{row.company ?? "—"}</div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <StatusBadge status={row.status} />
            <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-semibold text-secondary-foreground">
              fit {row.fitScore ?? "—"}
            </span>
          </div>
        </div>
        <p className="mt-4 line-clamp-3 whitespace-pre-line text-sm leading-6 text-muted-foreground">
          {row.jdText}
        </p>
      </button>
    </Card>
  );
}
