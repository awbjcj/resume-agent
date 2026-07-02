import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { AddUrlDialog } from "@/features/runs/AddUrlDialog";
import { DiscoverDialog, PullDialog } from "@/features/runs/RunLaunchDialogs";

import { ActionQueue } from "./ActionQueue";
import { DeskHealth } from "./DeskHealth";
import { RecentRuns } from "./RecentRuns";
import { StageRail } from "./StageRail";
import { useDashboardSummary } from "./use-dashboard-summary";

export function heroTitle(waiting: number): string {
  if (waiting === 0) return "Nothing is waiting on you";
  return `${waiting} job${waiting === 1 ? " is" : "s are"} waiting on you`;
}

export function DashboardPage() {
  const { data: summary, isPending } = useDashboardSummary();
  if (isPending || !summary) return <BoardSkeleton />;

  const waiting = Object.values(summary.queues).reduce((a, b) => a + b, 0);
  const totalJobs = Object.values(summary.statusCounts).reduce(
    (a, b) => a + b,
    0,
  );
  const eyebrow = `Operations · ${new Date().toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })}`;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        kicker={eyebrow}
        title={heroTitle(waiting)}
        sub="Pull fresh listings, triage the queue, and ship tailored resumes."
      />
      <div className="flex flex-wrap items-center gap-2">
        <PullDialog />
        <DiscoverDialog />
        <AddUrlDialog />
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-6">
          {totalJobs === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>Add sources and run your first pull</EmptyTitle>
                <EmptyDescription>
                  The funnel fills up once discovery has somewhere to look.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Button
                    render={<Link to="/settings/sources">Add sources</Link>}
                  />
                  <PullDialog />
                </div>
              </EmptyContent>
            </Empty>
          ) : (
            <>
              <ActionQueue summary={summary} />
              <StageRail summary={summary} />
            </>
          )}
          <RecentRuns />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <DeskHealth />
        </div>
      </div>
    </div>
  );
}
