import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SearchIcon } from "lucide-react";

import { BulkActionBar } from "@/components/BulkActionBar";
import { BulkPreviewButton } from "@/components/BulkPreviewButton";
import { EmptyState } from "@/components/EmptyState";
import { JobModal } from "@/components/JobModal";
import { MetricRow } from "@/components/MetricRow";
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
import { Slider } from "@/components/ui/slider";
import {
  type PipelineItem,
  useBoardQuery,
} from "@/features/board/use-board-query";
import { useBulkAction } from "@/features/board/use-bulk-action";
import { useSelection } from "@/features/board/use-selection";
import { useBulkRun } from "@/features/runs/use-bulk-run";
import { emptyFilterState } from "@/lib/filters/types";

import { PipelineCard } from "./PipelineCard";

const STAGE_ORDER = ["raw", "shortlisted", "approved", "tailored", "rendered", "rejected"];

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
  const { rows, total, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useBoardQuery<PipelineItem>("pipeline", filter);
  const selection = useSelection();
  const { reconcile } = selection;
  const bulk = useBulkAction("pipeline");
  const runs = useBulkRun();
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    reconcile(rows.map((row) => row.jobId), total);
  }, [rows, total, reconcile]);

  const byStage = useMemo(() => {
    const grouped = new Map<string, PipelineItem[]>();
    for (const row of rows) grouped.set(row.status, [...(grouped.get(row.status) ?? []), row]);
    return grouped;
  }, [rows]);

  if (isLoading) return <BoardSkeleton />;

  const stages = [
    ...STAGE_ORDER.filter((stage) => byStage.has(stage)),
    ...[...byStage.keys()].filter((stage) => !STAGE_ORDER.includes(stage)),
  ];
  const rendered = byStage.get("rendered")?.length ?? 0;
  const openId = params.get("job");
  const loadedIds = rows.map((row) => row.jobId);
  const bulkSelection = { mode: selection.mode, ids: selection.ids };
  const bulkArgs = { selection: bulkSelection, filter };
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
        className="mb-7 grid grid-cols-1 gap-4 rounded-lg border bg-card p-5 shadow-[0_1px_2px_rgba(24,32,38,0.04)] sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters();
        }}
      >
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
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="pipe-fit" className="text-xs font-semibold uppercase tracking-[0.14em]">
              Min fit
            </Label>
            <span className="text-xs tabular-nums text-muted-foreground">{draft.fitMin}</span>
          </div>
          <Slider
            id="pipe-fit"
            aria-label="Min fit"
            min={0}
            max={100}
            value={[draft.fitMin]}
            onValueChange={(value) => {
              const fit = (value as number[])[0] ?? 0;
              setFilterDraft({ ...draft, fitMin: normalizeFitInput(fit) ?? 0 });
            }}
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
                {STAGE_ORDER.map((stage) => (
                  <SelectItem key={stage} value={stage}>
                    {stage}
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
            <section key={stage} className="mb-8">
              <div className="mb-3 flex items-center justify-between border-b pb-2">
                <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  {stage}
                </h2>
                <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-semibold">
                  {byStage.get(stage)!.length}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
                {byStage.get(stage)!.map((row) => (
                  <PipelineCard
                    key={row.jobId}
                    row={row}
                    selected={selection.isSelected(row.jobId)}
                    onSelect={() =>
                      selection.toggle(row.jobId, loadedIds.indexOf(row.jobId), false, loadedIds)
                    }
                    onOpen={() => openJob(row.jobId)}
                  />
                ))}
              </div>
            </section>
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
