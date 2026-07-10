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
import {
  type TriageItem,
  useBoardQuery,
} from "@/features/board/use-board-query";
import { useBulkAction } from "@/features/board/use-bulk-action";
import { useSelection } from "@/features/board/use-selection";
import { useBoardFilters } from "@/features/shortlist/use-board-filters";

import { QuickFilters } from "./QuickFilters";

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

  if (isLoading) return <BoardSkeleton />;

  const openId = params.get("job");
  const loadedIds = rows.map((row) => row.jobId);
  const allLoadedSelected =
    rows.length > 0 && rows.every((row) => selection.isSelected(row.jobId));
  const bulkSelection = { mode: selection.mode, ids: selection.ids };
  const bulkArgs = { selection: bulkSelection, filter, archived };
  const action: "restore" | "archive" = archived ? "restore" : "archive";

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
      {openId && <JobModal jobId={Number(openId)} onClose={closeJob} />}
    </>
  );
}
