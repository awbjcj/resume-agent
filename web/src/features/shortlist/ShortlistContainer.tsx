import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import { BulkActionBar } from "@/components/BulkActionBar";
import { BulkPreviewButton } from "@/components/BulkPreviewButton";
import { EmptyState } from "@/components/EmptyState";
import { FilterDesk } from "@/components/FilterDesk";
import { JobCard } from "@/components/JobCard";
import { JobTable } from "@/components/JobTable";
import { JobModal } from "@/components/JobModal";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import {
  type ShortlistItem,
  useBoardQuery,
} from "@/features/board/use-board-query";
import { useBulkAction } from "@/features/board/use-bulk-action";
import { useSelection } from "@/features/board/use-selection";
import { BoardViewToggle } from "@/features/board/BoardViewToggle";
import { JobQuickActions } from "@/features/board/JobQuickActions";
import { useJobNavigation } from "@/features/board/use-job-navigation";
import { useViewMode } from "@/features/board/use-view-mode";
import { useApprove } from "./use-approve";
import { useBoardFilters } from "./use-board-filters";
import { ShortlistDetails } from "./ShortlistDetails";

export function ShortlistContainer() {
  const [filters, setFilters] = useBoardFilters();
  const { rows, facets, total, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, error } =
    useBoardQuery<ShortlistItem>("shortlist", filters);
  const selection = useSelection();
  const { reconcile } = selection;
  const bulk = useBulkAction("shortlist");
  const approve = useApprove();
  const [view, setView] = useViewMode("shortlist-view");
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
  if (error) return <EmptyState title="Failed to load" body={(error as Error).message} />;

  const avg = rows.length
    ? Math.round(rows.reduce((sum, row) => sum + (row.fitScore ?? 0), 0) / rows.length)
    : 0;
  const sponsored = rows.filter((row) => row.sponsorshipSignal === "offered").length;
  const bulkSelection = { mode: selection.mode, ids: selection.ids };
  const bulkArgs = { selection: bulkSelection, filter: filters };

  return (
    <>
      <PageHeader
        kicker="Human checkpoint"
        title="The Shortlist"
        sub="The cost gate before the premium tailoring step. Approve only the jobs worth the spend."
      />
      <MetricRow
        items={[
          ["Awaiting review", total.toLocaleString()],
          ["Avg fit in view", String(avg)],
          ["Sponsorship offered in view", String(sponsored)],
        ]}
      />
      <FilterDesk filter={filters} facets={facets} total={total} onChange={setFilters} />
      <div className="mb-5 flex justify-end">
        <BoardViewToggle view={view} onChange={setView} />
      </div>
      {!rows.length ? (
        <EmptyState
          title={total === 0 ? "Nothing shortlisted yet" : "No jobs loaded"}
          body="Run a discover to score jobs and surface the keepers here."
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
              label="Approve"
              title={`Approve ${selection.count.toLocaleString()} selected job(s)?`}
              preview={() => bulk.preview({ ...bulkArgs, action: "approve" })}
              run={() =>
                bulk.run({ ...bulkArgs, action: "approve" }).then((result) => {
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
          {view === "cards" ? <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            {rows.map((row) => (
              <JobCard
                key={row.jobId}
                row={row}
                activeSkills={filters.skills}
                selected={selection.isSelected(row.jobId)}
                onSelect={() =>
                  selection.toggle(row.jobId, loadedIds.indexOf(row.jobId), false, loadedIds)
                }
                onOpen={() => openJob(row.jobId)}
                footer={
                  <div className="flex items-center gap-2">
                    <Button className="flex-1" onClick={() => approve.mutate(row.jobId)}>Approve for tailoring</Button>
                    <JobQuickActions
                      jobId={row.jobId}
                      company={row.company}
                      url={row.url}
                      h1bStatus={row.h1BSponsorshipStatus}
                    />
                  </div>
                }
              />
            ))}
          </div> : (
            <JobTable
              rows={rows}
              selection={selection}
              onToggle={selection.toggle}
              onOpen={openJob}
              onToggleAll={(checked) => checked ? selection.selectPage(loadedIds) : selection.clear()}
              allChecked={rows.every((row) => selection.isSelected(row.jobId))}
              actions={(row) => <><Button size="sm" onClick={() => approve.mutate(row.jobId)}>Approve</Button><JobQuickActions jobId={row.jobId} company={row.company} url={row.url} h1bStatus={row.h1BSponsorshipStatus} /></>}
              statusColumn={false}
              extraColumn={{
                header: "Details",
                render: (row) => <ShortlistDetails row={row} />,
              }}
            />
          )}
          {hasNextPage && (
            <div className="mt-5 flex justify-center">
              <Button variant="outline" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
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
