import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BulkActionBar } from "@/components/BulkActionBar";
import { BulkPreviewButton } from "@/components/BulkPreviewButton";
import { EmptyState } from "@/components/EmptyState";
import { FilterDesk } from "@/components/FilterDesk";
import { JobModal } from "@/components/JobModal";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
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
import { LaunchDialog } from "@/features/runs/LaunchDialog";
import { useApprovedLaunchJobs } from "@/features/runs/use-approved-launch-jobs";
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

export function PipelineContainer() {
  const [filter, setFilter] = useState(pipelineFilter);
  const [targetStatus, setTargetStatus] = useState("approved");
  const [launchMode, setLaunchMode] = useState<"tailor" | "coverLetter" | null>(null);
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
  const launchJobs = useApprovedLaunchJobs(launchMode !== null);

  useEffect(() => {
    reconcile(rows.map((row) => row.jobId), total);
  }, [rows, total, reconcile]);

  const byStage = useMemo(() => {
    const grouped = new Map<string, PipelineItem[]>();
    for (const row of rows) {
      const bucket = grouped.get(row.status);
      if (bucket) bucket.push(row);
      else grouped.set(row.status, [row]);
    }
    return grouped;
  }, [rows]);

  if (isLoading) return <BoardSkeleton />;

  const stages = orderPipelineStages(byStage.keys());
  const rendered = byStage.get("rendered")?.length ?? 0;
  const openId = params.get("job");
  const loadedIds = rows.map((row) => row.jobId);
  const bulkSelection = { mode: selection.mode, ids: selection.ids };
  const bulkArgs = { selection: bulkSelection, filter };
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
        <Button variant="outline" size="sm" onClick={() => setLaunchMode("tailor")}>
          Tailor approved…
        </Button>
        <Button variant="outline" size="sm" onClick={() => setLaunchMode("coverLetter")}>
          Cover letters…
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
      <FilterDesk
        filter={filter}
        facets={facets}
        total={total}
        onChange={setFilter}
        statusOptions={PIPELINE_STAGE_ORDER}
        statusLabel={pipelineStageLabel}
      />
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
      <LaunchDialog
        mode={launchMode ?? "tailor"}
        jobs={launchJobs.jobs}
        open={launchMode !== null}
        isLoading={launchJobs.isLoading}
        error={launchJobs.error}
        onRetry={() => void launchJobs.retry()}
        onOpenChange={(open) => {
          if (!open) setLaunchMode(null);
        }}
        onLaunch={(jobIds, deep) =>
          launchMode === "coverLetter"
            ? runs.coverLettersSelected(jobIds)
            : runs.tailorSelected(jobIds, deep)
        }
      />
    </>
  );
}
