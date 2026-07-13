import type { ReactNode } from "react";
import { ChevronDownIcon } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { JobTable } from "@/components/JobTable";
import type { ViewMode } from "@/features/board/use-view-mode";

import { PipelineCard } from "./PipelineCard";
import { pipelineStageLabel } from "./pipeline-stages";
import type { PipelineItem } from "./use-pipeline";

type PipelineStageSectionProps = {
  stage: string;
  rows: PipelineItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isSelected: (jobId: number) => boolean;
  onSelect: (row: PipelineItem) => void;
  onToggleAll: (checked: boolean) => void;
  onOpen: (row: PipelineItem) => void;
  view: ViewMode;
  actions: (row: PipelineItem) => ReactNode;
};

export function PipelineStageSection({
  stage,
  rows,
  open,
  onOpenChange,
  isSelected,
  onSelect,
  onToggleAll,
  onOpen,
  view,
  actions,
}: PipelineStageSectionProps) {
  const countLabel = `${rows.length.toLocaleString()} ${rows.length === 1 ? "job" : "jobs"}`;

  return (
    <section className="mb-6">
      <Collapsible open={open} onOpenChange={onOpenChange}>
        <CollapsibleTrigger
          className={cn(
            buttonVariants({ variant: "ghost" }),
            "group h-auto min-h-11 w-full justify-between whitespace-normal rounded-lg border bg-card px-4 py-3 text-left shadow-[0_1px_2px_rgba(24,32,38,0.04)] hover:border-primary/25",
          )}
        >
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            {pipelineStageLabel(stage)}
          </h2>
          <span className="ml-auto text-xs font-semibold tabular-nums text-muted-foreground">
            {countLabel}
          </span>
          <ChevronDownIcon
            data-icon="inline-end"
            className="text-muted-foreground transition-transform group-data-panel-open:rotate-180"
          />
        </CollapsibleTrigger>
        <CollapsibleContent>
          {view === "list" ? <div className="pt-4"><JobTable
            rows={rows}
            selection={{ isSelected }}
            onToggle={(id) => { const row = rows.find((item) => item.jobId === id); if (row) onSelect(row); }}
            onToggleAll={onToggleAll}
            allChecked={rows.every((row) => isSelected(row.jobId))}
            onOpen={(id) => { const row = rows.find((item) => item.jobId === id); if (row) onOpen(row); }}
            actions={(row) => actions(row as PipelineItem)}
          /></div> : <div className="grid grid-cols-1 gap-4 pt-4 xl:grid-cols-2 2xl:grid-cols-3">
            {rows.map((row) => (
              <PipelineCard
                key={row.jobId}
                row={row}
                selected={isSelected(row.jobId)}
                onSelect={() => onSelect(row)}
                onOpen={() => onOpen(row)}
                footer={actions(row)}
              />
            ))}
          </div>}
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
