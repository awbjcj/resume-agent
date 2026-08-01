import { useEffect, useMemo, type ReactNode } from "react";
import { ChevronDownIcon } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { JobTable } from "@/components/JobTable";
import { useBoardQuery } from "@/features/board/use-board-query";
import type { ViewMode } from "@/features/board/use-view-mode";
import type { FilterState } from "@/lib/filters/types";

import { PipelineCard } from "./PipelineCard";
import { PipelineDetails } from "./PipelineDetails";
import { pipelineStageLabel } from "./pipeline-stages";
import type { PipelineItem } from "./use-pipeline";

const STAGE_PAGE_SIZE = 20;

type PipelineStageSectionProps = {
  stage: string;
  filter: FilterState;
  /** Total jobs in this stage (from the board facets) — accurate even when the
   * section is collapsed and its rows have not been fetched. */
  total: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isSelected: (jobId: number) => boolean;
  onToggle: (jobId: number, index: number, ordered: number[]) => void;
  onSelectAll: (ids: number[]) => void;
  onClear: () => void;
  onOpen: (row: PipelineItem) => void;
  onRowsChange: (stage: string, rows: PipelineItem[]) => void;
  view: ViewMode;
  actions: (row: PipelineItem) => ReactNode;
};

export function PipelineStageSection({
  stage,
  filter,
  total,
  open,
  onOpenChange,
  isSelected,
  onToggle,
  onSelectAll,
  onClear,
  onOpen,
  onRowsChange,
  view,
  actions,
}: PipelineStageSectionProps) {
  // Each stage owns an independent, status-scoped query so every stage that has
  // jobs always renders — no stage can be paginated out of view by another.
  // Rows are fetched lazily on first expand to avoid N queries up front.
  const stageFilter = useMemo<FilterState>(
    () => ({ ...filter, status: new Set([stage]) }),
    [filter, stage],
  );
  const { rows, hasNextPage, fetchNextPage, isFetchingNextPage, isLoading } =
    useBoardQuery<PipelineItem>("pipeline", stageFilter, {
      pageSize: STAGE_PAGE_SIZE,
      enabled: open,
    });

  useEffect(() => {
    onRowsChange(stage, rows);
  }, [stage, rows, onRowsChange]);

  const orderedIds = rows.map((row) => row.jobId);
  const allChecked = rows.length > 0 && rows.every((row) => isSelected(row.jobId));
  const countLabel = `${total.toLocaleString()} ${total === 1 ? "job" : "jobs"}`;

  return (
    <section className="mb-6">
      <Collapsible open={open} onOpenChange={onOpenChange}>
        <CollapsibleTrigger
          className={cn(
            buttonVariants({ variant: "ghost" }),
            "group h-auto min-h-11 w-full justify-between whitespace-normal rounded-lg border bg-card px-4 py-3 text-left shadow-card hover:border-primary/25",
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
          {isLoading ? (
            <p className="px-1 pt-4 text-sm text-muted-foreground" role="status">
              Loading {pipelineStageLabel(stage).toLowerCase()} jobs…
            </p>
          ) : view === "list" ? (
            <div className="pt-4">
              <JobTable
                rows={rows}
                selection={{ isSelected }}
                onToggle={(id) => {
                  const index = orderedIds.indexOf(id);
                  if (index >= 0) onToggle(id, index, orderedIds);
                }}
                onToggleAll={(checked) => (checked ? onSelectAll(orderedIds) : onClear())}
                allChecked={allChecked}
                onOpen={(id) => {
                  const row = rows.find((item) => item.jobId === id);
                  if (row) onOpen(row);
                }}
                actions={(row) => actions(row as PipelineItem)}
                extraColumn={{
                  header: "Details",
                  render: (row) => <PipelineDetails row={row} />,
                }}
              />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 pt-4 xl:grid-cols-2 2xl:grid-cols-3">
              {rows.map((row) => (
                <PipelineCard
                  key={row.jobId}
                  row={row}
                  selected={isSelected(row.jobId)}
                  onSelect={() => {
                    const index = orderedIds.indexOf(row.jobId);
                    onToggle(row.jobId, index, orderedIds);
                  }}
                  onOpen={() => onOpen(row)}
                  footer={actions(row)}
                />
              ))}
            </div>
          )}
          {hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage
                  ? "Loading…"
                  : `Load more ${pipelineStageLabel(stage).toLowerCase()}`}
              </Button>
            </div>
          )}
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
