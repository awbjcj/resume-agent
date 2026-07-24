import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BulkActionBar } from "@/components/BulkActionBar";
import { BulkPreviewButton } from "@/components/BulkPreviewButton";
import { EmptyState } from "@/components/EmptyState";
import { FilterDesk } from "@/components/FilterDesk";
import { JobModal } from "@/components/JobModal";
import { JobTable } from "@/components/JobTable";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useBoardQuery, type TriageItem } from "@/features/board/use-board-query";
import { useBulkAction } from "@/features/board/use-bulk-action";
import { useJobNavigation } from "@/features/board/use-job-navigation";
import { useSelection } from "@/features/board/use-selection";
import { JobQuickActions } from "@/features/board/JobQuickActions";
import { useBoardFilters } from "@/features/shortlist/use-board-filters";
import { recency } from "@/lib/format";

import { QuickFilters } from "./QuickFilters";
import { ImportJobsButton } from "@/features/runs/ImportJobsDialog";

type TriageNoteRow = {
  rejectReason?: string | null;
  postedAt?: string | null;
};

function TriageNote({ row }: { row: TriageNoteRow }) {
  if (row.rejectReason) {
    return (
      <div className="border-l-2 border-destructive/45 pl-3">
        <div className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-destructive">
          Rejection reason
        </div>
        <p className="mt-1 whitespace-normal break-words text-sm leading-5 text-foreground">
          {row.rejectReason}
        </p>
      </div>
    );
  }
  const posted = recency(row.postedAt);
  return posted ? (
    <dl>
      <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground/75">
        Posted
      </dt>
      <dd className="mt-0.5 text-sm leading-5 text-foreground">{posted}</dd>
    </dl>
  ) : null;
}

export function TriageContainer() {
  const [archived, setArchived] = useState(false);
  const [filter, setFilter] = useBoardFilters();
  const { rows, facets, total, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useBoardQuery<TriageItem>("triage", filter, { archived });
  const selection = useSelection();
  const { reconcile } = selection;
  const bulk = useBulkAction("triage");
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    reconcile(rows.map((row) => row.jobId), total);
  }, [rows, total, reconcile]);

  const openId = params.get("job");
  const loadedIds = rows.map((row) => row.jobId);

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

  const nav = useJobNavigation(
    loadedIds,
    openId ? Number(openId) : null,
    openJob,
    { hasNextPage, isFetchingNextPage, fetchNextPage },
  );

  if (isLoading) return <BoardSkeleton />;

  const allLoadedSelected =
    rows.length > 0 && rows.every((row) => selection.isSelected(row.jobId));
  const bulkSelection = { mode: selection.mode, ids: selection.ids };
  const bulkArgs = { selection: bulkSelection, filter, archived };
  const action: "restore" | "archive" = archived ? "restore" : "archive";

  return (
    <>
      <PageHeader
        kicker="Intake"
        title="Triage Desk"
        sub="Raw and rejected jobs before the shortlist. Archive noise, delete dead-ends, prune in bulk."
      />
      <MetricRow
        items={[
          ["Loaded", rows.length.toLocaleString()],
          ["Matching", total.toLocaleString()],
        ]}
      />
      <FilterDesk filter={filter} facets={facets} total={total} onChange={setFilter} />
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Switch id="show-archived" checked={archived} onCheckedChange={setArchived} />
          <Label htmlFor="show-archived" className="text-sm font-medium">
            Show archived
          </Label>
        </div>
        <span aria-hidden className="h-4 w-px bg-border" />
        <QuickFilters onApply={(patch) => setFilter({ ...filter, ...patch })} />
        <ImportJobsButton />
      </div>
      {!rows.length ? (
        <EmptyState
          title="Nothing to triage"
          body="Run a pull to bring in jobs, or toggle archived."
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
            <BulkPreviewButton
              label={archived ? "Restore" : "Archive"}
              title={`${archived ? "Restore" : "Archive"} ${selection.count.toLocaleString()} selected job(s)?`}
              preview={() => bulk.preview({ ...bulkArgs, action })}
              run={() =>
                bulk.run({ ...bulkArgs, action }).then((result) => {
                  selection.clear();
                  return result;
                })
              }
            />
            <BulkPreviewButton
              label="Delete"
              title={`Delete ${selection.count.toLocaleString()} selected job(s)?`}
              confirmLabel="Confirm delete"
              variant="destructive"
              preview={() => bulk.preview({ ...bulkArgs, action: "delete" })}
              run={() =>
                bulk.run({ ...bulkArgs, action: "delete" }).then((result) => {
                  selection.clear();
                  return result;
                })
              }
            />
          </BulkActionBar>
          <JobTable
            rows={rows}
            selection={selection}
            onToggle={selection.toggle}
            onOpen={openJob}
            onToggleAll={(checked) => (checked ? selection.selectPage(loadedIds) : selection.clear())}
            allChecked={allLoadedSelected}
            actions={(row) => (
              <JobQuickActions
                jobId={row.jobId}
                url={row.url}
                archived={archived}
                allowDelete
              />
            )}
            statusColumn={false}
            extraColumn={{
              header: "Notes",
              render: (row) => <TriageNote row={row} />,
              width: "wide",
            }}
          />
          {hasNextPage && (
            <div className="mt-5 flex justify-center">
              <Button
                variant="outline"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? "Loading..." : "Load more"}
              </Button>
            </div>
          )}
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
    </>
  );
}
