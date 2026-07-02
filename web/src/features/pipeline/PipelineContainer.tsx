import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SearchIcon } from "lucide-react";

import { BulkActionBar } from "@/components/BulkActionBar";
import { BulkPreviewButton } from "@/components/BulkPreviewButton";
import { EmptyState } from "@/components/EmptyState";
import { FacetPopover } from "@/components/filters/FacetPopover";
import { JobModal } from "@/components/JobModal";
import { MetricRow } from "@/components/MetricRow";
import { MinFitInput } from "@/components/MinFitInput";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type PipelineItem,
  useBoardQuery,
} from "@/features/board/use-board-query";
import { useBulkAction } from "@/features/board/use-bulk-action";
import { useSelection } from "@/features/board/use-selection";
import { useBulkRun } from "@/features/runs/use-bulk-run";
import { emptyFilterState } from "@/lib/filters/types";

import { PipelineStageSection } from "./PipelineStageSection";
import {
  openStagesFromParam,
  orderPipelineStages,
  PIPELINE_STAGE_ORDER,
  pipelineStageLabel,
} from "./pipeline-stages";

function pipelineFilter() {
  const filter = emptyFilterState();
  filter.sort = "stage";
  return filter;
}

function normalizeFitInput(value: number) {
  const fit = Math.min(100, Math.max(0, Math.round(value)));
  return fit === 0 ? null : fit;
}

type PipelineFilterDraft = {
  sourceQ: string;
  sourceFitMin: number | null;
  q: string;
  fitMin: number;
};

function pipelineDraftFromFilter(filter: ReturnType<typeof pipelineFilter>): PipelineFilterDraft {
  return {
    sourceQ: filter.q,
    sourceFitMin: filter.fitMin,
    q: filter.q,
    fitMin: filter.fitMin ?? 0,
  };
}

function isPipelineDraftCurrent(
  draft: PipelineFilterDraft,
  filter: ReturnType<typeof pipelineFilter>,
) {
  return draft.sourceQ === filter.q && draft.sourceFitMin === filter.fitMin;
}

export function PipelineContainer() {
  const [filter, setFilter] = useState(pipelineFilter);
  const [filterDraft, setFilterDraft] = useState(() => pipelineDraftFromFilter(filter));
  const draft = isPipelineDraftCurrent(filterDraft, filter)
    ? filterDraft
    : pipelineDraftFromFilter(filter);
  const [targetStatus, setTargetStatus] = useState("approved");
  const [params, setParams] = useSearchParams();
  const [openStages, setOpenStages] = useState(() =>
    openStagesFromParam(params.get("stage")),
  );
  const { rows, facets, total, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useBoardQuery<PipelineItem>("pipeline", filter);
  const selection = useSelection();
  const { reconcile } = selection;
  const bulk = useBulkAction("pipeline");
  const runs = useBulkRun();

  useEffect(() => {
    reconcile(rows.map((row) => row.jobId), total);
  }, [rows, total, reconcile]);

  const byStage = useMemo(() => {
    const grouped = new Map<string, PipelineItem[]>();
    for (const row of rows) grouped.set(row.status, [...(grouped.get(row.status) ?? []), row]);
    return grouped;
  }, [rows]);

  if (isLoading) return <BoardSkeleton />;

  const stages = orderPipelineStages(byStage.keys());
  const rendered = byStage.get("rendered")?.length ?? 0;
  const openId = params.get("job");
  const loadedIds = rows.map((row) => row.jobId);
  const bulkSelection = { mode: selection.mode, ids: selection.ids };
  const bulkArgs = { selection: bulkSelection, filter };
  const statusCounts = Object.fromEntries(
    PIPELINE_STAGE_ORDER.map((stage) => [stage, facets.status?.[stage] ?? 0]),
  );
  for (const [status, count] of Object.entries(facets.status ?? {})) statusCounts[status] = count;
  for (const status of filter.status) statusCounts[status] ??= 0;
  const committedQ = draft.q.trim();
  const committedFitMin = normalizeFitInput(draft.fitMin);
  const hasFilterDraftChanges =
    committedQ !== filter.q.trim() || committedFitMin !== filter.fitMin;
  const applyFilters = () => {
    if (!hasFilterDraftChanges) return;
    setFilter({ ...filter, q: committedQ, fitMin: committedFitMin });
    setFilterDraft({
      sourceQ: committedQ,
      sourceFitMin: committedFitMin,
      q: committedQ,
      fitMin: committedFitMin ?? 0,
    });
  };
  const setStageOpen = (stage: string, open: boolean) => {
    setOpenStages((current) => {
      const next = new Set(current);
      if (open) next.add(stage);
      else next.delete(stage);
      return next;
    });
  };

  const openJob = (id: number) =>
    setParams(
      (p) => {
        p.set("job", String(id));
        return p;
      },
      { replace: true },
    );
  const closeJob = () =>
    setParams(
      (p) => {
        p.delete("job");
        return p;
      },
      { replace: true },
    );

  return (
    <>
      <PageHeader
        kicker="Mission control"
        title="Pipeline / Board"
        sub="Every job by pipeline stage, with its tailored PDF, review critiques, and your application status."
      />
      <div className="mb-5 flex flex-wrap gap-2 rounded-lg border bg-card p-3 shadow-[0_1px_2px_rgba(24,32,38,0.04)]">
        <Button variant="outline" size="sm" onClick={runs.tailorApproved}>
          Tailor approved
        </Button>
        <Button variant="outline" size="sm" onClick={runs.coverLettersApproved}>
          Cover letters (approved)
        </Button>
      </div>
      <MetricRow
        items={[
          ["Loaded", rows.length.toLocaleString()],
          ["Matching", total.toLocaleString()],
          ["Rendered in view", String(rendered)],
          ["Stages active", String(byStage.size)],
        ]}
      />
      <form
        className="mb-7 grid grid-cols-1 gap-4 rounded-lg border bg-card p-5 shadow-[0_1px_2px_rgba(24,32,38,0.04)] sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(10rem,0.6fr)_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-[0.14em]">
            Status
          </span>
          <FacetPopover
            label="Status"
            counts={statusCounts}
            selected={filter.status}
            onChange={(status) => setFilter({ ...filter, status })}
            getLabel={pipelineStageLabel}
            presentation="field"
          />
        </div>
        <MinFitInput
          id="pipe-fit"
          value={draft.fitMin}
          onChange={(fitMin) => setFilterDraft({ ...draft, fitMin })}
        />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pipe-q" className="text-xs font-semibold uppercase tracking-[0.14em]">
            Company/title
          </Label>
          <Input
            id="pipe-q"
            className="h-10 bg-card"
            value={draft.q}
            onChange={(event) => setFilterDraft({ ...draft, q: event.target.value })}
          />
        </div>
        <div className="flex items-end">
          <Button type="submit" className="w-full lg:w-auto" disabled={!hasFilterDraftChanges}>
            <SearchIcon data-icon="inline-start" />
            Apply filters
          </Button>
        </div>
      </form>
      {!rows.length ? (
        <EmptyState
          title="No jobs in the pipeline"
          body="Start by adding a job or running a pull."
        />
      ) : (
        <>
          <BulkActionBar
            count={selection.count}
            isAllMatching={selection.isAllMatching}
            pageCount={rows.length}
            total={total}
            onSelectAllMatching={() => selection.selectAllMatching(total)}
            onClear={selection.clear}
          >
            <Select
              value={targetStatus}
              onValueChange={(value) => {
                if (value) setTargetStatus(value);
              }}
            >
              <SelectTrigger size="sm" className="bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PIPELINE_STAGE_ORDER.map((stage) => (
                  <SelectItem key={stage} value={stage}>
                    {pipelineStageLabel(stage)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <BulkPreviewButton
              label="Set status"
              title={`Set ${selection.count.toLocaleString()} selected job(s) to ${targetStatus}?`}
              preview={() =>
                bulk.preview({ ...bulkArgs, action: "setStatus", status: targetStatus })
              }
              run={() =>
                bulk
                  .run({ ...bulkArgs, action: "setStatus", status: targetStatus })
                  .then((result) => {
                    selection.clear();
                    return result;
                  })
              }
            />
            <BulkPreviewButton
              label="Archive"
              title={`Archive ${selection.count.toLocaleString()} selected job(s)?`}
              preview={() => bulk.preview({ ...bulkArgs, action: "archive" })}
              run={() =>
                bulk.run({ ...bulkArgs, action: "archive" }).then((result) => {
                  selection.clear();
                  return result;
                })
              }
            />
          </BulkActionBar>
          {stages.map((stage) => (
            <PipelineStageSection
              key={stage}
              stage={stage}
              rows={byStage.get(stage)!}
              open={openStages.has(stage)}
              onOpenChange={(open) => setStageOpen(stage, open)}
              isSelected={selection.isSelected}
              onSelect={(row) =>
                selection.toggle(row.jobId, loadedIds.indexOf(row.jobId), false, loadedIds)
              }
              onOpen={(row) => openJob(row.jobId)}
            />
          ))}
          {hasNextPage && (
            <div className="mt-5 flex justify-center">
              <Button variant="outline" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
                {isFetchingNextPage ? "Loading..." : "Load more"}
              </Button>
            </div>
          )}
        </>
      )}
      {openId && <JobModal jobId={Number(openId)} onClose={closeJob} />}
    </>
  );
}
