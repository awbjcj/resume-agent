import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import type { PipelineItem } from "./use-pipeline";

export function PipelineCard({ row, onOpen }: { row: PipelineItem; onOpen: () => void }) {
  return (
    <Card className="p-4">
      <button onClick={onOpen} className="w-full text-left">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-serif text-base font-semibold">{row.title ?? "—"}</div>
            <div className="text-sm text-muted-foreground">{row.company ?? "—"}</div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={row.status} />
            <span className="font-mono text-xs">fit {row.fitScore ?? "—"}</span>
          </div>
        </div>
        <p className="mt-2 line-clamp-3 whitespace-pre-line text-sm text-muted-foreground">
          {row.jdText}
        </p>
      </button>
    </Card>
  );
}
