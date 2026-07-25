import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/StatusBadge";
import type { PipelineItem } from "./use-pipeline";

export function PipelineCard({
  row,
  onOpen,
  selected,
  onSelect,
  footer,
}: {
  row: PipelineItem;
  onOpen: () => void;
  selected?: boolean;
  onSelect?: (checked: boolean) => void;
  footer?: ReactNode;
}) {
  return (
    <Card className="min-w-0 flex-col gap-4 p-5 transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_16px_40px_rgba(24,32,38,0.08)]">
      <div className="flex items-start gap-3">
      {onSelect && (
        <div className="pt-1">
          <Checkbox
            checked={selected}
            onCheckedChange={(value) => onSelect(Boolean(value))}
            aria-label={`Select ${row.company ?? "job"} ${row.title ?? ""}`.trim()}
          />
        </div>
      )}
      <button
        type="button"
        onClick={onOpen}
        className="group block min-w-0 flex-1 rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1 basis-56">
            <div className="break-words text-lg font-semibold leading-snug group-hover:text-primary">
              {row.title ?? "—"}
            </div>
            <div className="mt-1 text-sm text-muted-foreground">{row.company ?? "—"}</div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            <StatusBadge status={row.status} />
            <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-semibold text-secondary-foreground">
              fit {row.fitScore ?? "—"}
            </span>
          </div>
        </div>
        <p className="mt-4 line-clamp-3 break-words whitespace-pre-line text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">
          {row.jdPreview}
        </p>
      </button>
      </div>
      {footer && <div className="mt-auto flex justify-end gap-1 border-t pt-4">{footer}</div>}
    </Card>
  );
}
