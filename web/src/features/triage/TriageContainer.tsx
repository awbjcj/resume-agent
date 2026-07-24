import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BulkActionBar } from "@/components/BulkActionBar";
import { BulkPreviewButton } from "@/components/BulkPreviewButton";
import { EmptyState } from "@/components/EmptyState";
import { JobModal } from "@/components/JobModal";
import { JobTable } from "@/components/JobTable";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { useBoardQuery, type TriageItem } from "@/features/board/use-board-query";
import { useBulkAction } from "@/features/board/use-bulk-action";
import { useJobNavigation } from "@/features/board/use-job-navigation";
import { useSelection } from "@/features/board/use-selection";
import { JobQuickActions } from "@/features/board/JobQuickActions";
import { useBoardFilters } from "@/features/shortlist/use-board-filters";
import { recency } from "@/lib/format";
import type { FilterState } from "@/lib/filters/types";

import { TriageFilters } from "./TriageFilters";

type TriageNoteRow = {
  status?: string;
  rejectReason?: string | null;
  rejectCategory?: string | null;
  postedAt?: string | null;
};

function TriageNote({ row }: { row: TriageNoteRow }) {
  if (row.rejectReason) {
    const label =
      row.status === "filtered" || row.rejectCategory === "filtered"
        ? "Filtered out"
        : "Rejected";
    return (
      <div
        className="flex min-w-0 items-center gap-2 overflow-hidden whitespace-nowrap"
        title={row.rejectReason}
      >
        <span
          aria-hidden
          className="size-1.5 shrink-0 rounded-full bg-destructive"
        />
        <span
          className="min-w-0 truncate text-sm text-destructive"
          aria-label={`${label}: ${row.rejectReason}`}
        >
          <span className="font-medium">{label}:</span> {row.rejectReason}
        </span>
      </div>
    );
  }
  const posted = recency(row.postedAt);
  return posted ? (
    <span className="whitespace-nowrap text-sm text-foreground">Posted {posted}</span>
  ) : null;
}

export function TriageContainer() {
  const [archived, setArchived] = useState(false);
  const [rawFilter, setRawFilter] = useBoardFilters("recency");
  const filter: FilterState = { ...rawFilter, fitMin: null, maxFit: null };
  const setFilter = (next: FilterState) =>
    setRawFilter({ ...next, fitMin: null, maxFit: null });
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
      <TriageFilters
        filter={filter}
        facets={facets}
        total={total}
        archived={archived}
        onArchivedChange={setArchived}
        onChange={setFilter}
      />
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
            fitColumn={false}
            extraColumn={{
              header: "Notes",
              render: (row) => <TriageNote row={row} />,
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
