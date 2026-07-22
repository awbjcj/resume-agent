import { PageHeader } from "@/components/PageHeader";
import { BoardSkeleton } from "@/components/skeletons";
import { AddUrlDialog } from "@/features/runs/AddUrlDialog";
import { ImportJobsButton } from "@/features/runs/ImportJobsDialog";
import { DiscoverDialog, PullDialog } from "@/features/runs/RunLaunchDialogs";
import { GettingStartedChecklist } from "@/features/journey/GettingStartedChecklist";
import { JourneyRail } from "@/features/journey/JourneyRail";

import { ActionQueue } from "./ActionQueue";
import { AttentionCard } from "./AttentionCard";
import { DeskHealth } from "./DeskHealth";
import { InProgressCard } from "./InProgressCard";
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
  // rejected is terminal-negative and never appears on the rail/queues (see
  // StageRail), so it must not count toward "the funnel has jobs in it".
  const totalJobs = Object.entries(summary.statusCounts).reduce(
    (sum, [status, count]) => (status === "rejected" ? sum : sum + count),
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
      <GettingStartedChecklist />
      <div className="flex flex-wrap items-center gap-2">
        <PullDialog />
        <DiscoverDialog />
        <AddUrlDialog />
        <ImportJobsButton />
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <JourneyRail />
          {/* When the funnel has no active jobs the JourneyRail already carries
              the right next step (add sources, or pull), so no separate empty
              card is needed — it would only duplicate that guidance. */}
          {totalJobs > 0 && (
            <>
              <ActionQueue summary={summary} />
              <StageRail summary={summary} />
            </>
          )}
          <InProgressCard summary={summary} />
          <AttentionCard />
          <RecentRuns />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <DeskHealth />
        </div>
      </div>
    </div>
  );
}
