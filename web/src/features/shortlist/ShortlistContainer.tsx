import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { BoardSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { FilterDesk } from "@/components/FilterDesk";
import { JobCard } from "@/components/JobCard";
import { JobModal } from "@/components/JobModal";
import { applyFilters } from "@/lib/filters/apply";
import { sortRows } from "@/lib/filters/sort";
import { useShortlist } from "./use-shortlist";
import { useBoardFilters } from "./use-board-filters";
import { useApprove } from "./use-approve";

export function ShortlistContainer() {
  const { data: rows, isLoading, error } = useShortlist();
  const [filters, setFilters] = useBoardFilters();
  const approve = useApprove();
  const [params, setParams] = useSearchParams();

  const visible = useMemo(
    () => (rows ? sortRows(applyFilters(rows, filters), filters) : []),
    [rows, filters],
  );

  if (isLoading) return <BoardSkeleton />;
  if (error) return <EmptyState title="Failed to load" body={(error as Error).message} />;

  const avg = rows?.length
    ? Math.round(rows.reduce((a, r) => a + (r.fitScore ?? 0), 0) / rows.length)
    : 0;
  const sponsored = rows?.filter((r) => r.sponsorshipSignal === "offered").length ?? 0;
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

  return (
    <>
      <PageHeader
        kicker="Human checkpoint"
        title="The Shortlist"
        sub="The cost gate before the premium tailoring step. Approve only the jobs worth the spend."
      />
      <MetricRow
        items={[
          ["Awaiting review", String(rows?.length ?? 0)],
          ["Avg fit", String(avg)],
          ["Sponsorship offered", String(sponsored)],
        ]}
      />
      {!rows?.length ? (
        <EmptyState
          title="Nothing shortlisted yet"
          body="Run a discover to score jobs and surface the keepers here."
        />
      ) : (
        <>
          <FilterDesk rows={rows} state={filters} onChange={setFilters} />
          {visible.length === 0 ? (
            <EmptyState
              title="No jobs match these filters"
              body="Loosen a filter or clear the skill tags."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
              {visible.map((row) => (
                <JobCard
                  key={row.jobId}
                  row={row}
                  activeSkills={filters.skills}
                  onOpen={() => openJob(row.jobId)}
                  footer={
                    <Button className="w-full" onClick={() => approve.mutate(row.jobId)}>
                      Approve for tailoring
                    </Button>
                  }
                />
              ))}
            </div>
          )}
        </>
      )}
      {openId && <JobModal jobId={Number(openId)} onClose={closeJob} />}
    </>
  );
}
