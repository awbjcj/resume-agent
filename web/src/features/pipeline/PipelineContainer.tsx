import { useCallback, useEffect, useMemo, useState } from "react";
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
import { BoardViewToggle } from "@/features/board/BoardViewToggle";
import { JobQuickActions } from "@/features/board/JobQuickActions";
import { useJobNavigation } from "@/features/board/use-job-navigation";
import { useViewMode } from "@/features/board/use-view-mode";
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
  // A lightweight overview query drives the facets (which stages exist and how
  // many jobs each holds) and the overall matching total. Rows come from the
  // per-stage sections, so this query only needs a single row.
  const { facets, total, isLoading } = useBoardQuery<PipelineItem>("pipeline", filter, {
    pageSize: 1,
  });
  const selection = useSelection();
  const { reconcile } = selection;
  const bulk = useBulkAction("pipeline");
  const runs = useBulkRun();
  const launchJobs = useApprovedLaunchJobs(launchMode !== null);
  const [view, setView] = useViewMode("pipeline-view");
  // Rows loaded by each open stage section, mirrored here so bulk selection and
  // the metric row can reason across the whole board.
  const [loadedByStage, setLoadedByStage] = useState<Record<string, PipelineItem[]>>({});

  const reportRows = useCallback((stage: string, rows: PipelineItem[]) => {
    setLoadedByStage((prev) => {
      const existing = prev[stage];
      if (
        existing &&
        existing.length === rows.length &&
        existing.every((row, index) => row.jobId === rows[index].jobId)
      ) {
        return prev;
      }
      return { ...prev, [stage]: rows };
    });
  }, []);

  const stageCounts = (facets.status ?? {}) as Record<string, number>;
  const stages = useMemo(() => {
    const counts = (facets.status ?? {}) as Record<string, number>;
    // A status filter narrows which stage sections show; without one, every
    // stage that has jobs renders.
    const allow = filter.status.size ? filter.status : null;
    return orderPipelineStages(
      Object.keys(counts).filter(
        (stage) => counts[stage] > 0 && (!allow || allow.has(stage)),
      ),
    );
  }, [facets, filter.status]);
  const loadedRows = useMemo(
    () => stages.flatMap((stage) => loadedByStage[stage] ?? []),
    [stages, loadedByStage],
  );
  const loadedIds = useMemo(() => loadedRows.map((row) => row.jobId), [loadedRows]);

  useEffect(() => {
    reconcile(loadedIds, total);
  }, [loadedIds, total, reconcile]);

  const openId = params.get("job");

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

  const nav = useJobNavigation(loadedIds, openId ? Number(openId) : null, openJob);

  if (isLoading) return <BoardSkeleton />;

  const rendered = loadedByStage.rendered?.length ?? 0;
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
        <div className="ml-auto"><BoardViewToggle view={view} onChange={setView} /></div>
      </div>
      <MetricRow
        items={[
          ["Loaded", loadedRows.length.toLocaleString()],
          ["Matching", total.toLocaleString()],
          ["Rendered in view", String(rendered)],
          ["Stages active", String(stages.length)],
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
      {!stages.length ? (
        <EmptyState
          title="No jobs in the pipeline"
          body="Start by adding a job or running a pull."
        />
      ) : (
        <>
          <BulkActionBar
            count={selection.count}
            isAllMatching={selection.isAllMatching}
            pageCount={loadedRows.length}
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
              filter={filter}
              total={stageCounts[stage] ?? 0}
              open={openStages.has(stage)}
              onOpenChange={(open) => setStageOpen(stage, open)}
              isSelected={selection.isSelected}
              onToggle={(jobId, index, ordered) =>
                selection.toggle(jobId, index, false, ordered)
              }
              onSelectAll={(ids) => selection.selectPage(ids)}
              onClear={selection.clear}
              onOpen={(row) => openJob(row.jobId)}
              onRowsChange={reportRows}
              view={view}
              actions={(row) => <JobQuickActions jobId={row.jobId} url={row.url} />}
            />
          ))}
        </>
      )}
      {openId && (
        <JobModal
          jobId={Number(openId)}
          onClose={closeJob}
          onPrev={nav.goPrev}
          onNext={nav.goNext}
          hasPrev={nav.hasPrev}
          hasNext={nav.hasNext}
          isLoadingNext={nav.isLoadingNext}
        />
      )}
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
