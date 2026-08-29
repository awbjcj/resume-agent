import { PageHeader } from "@/components/PageHeader";
import { useTranslation } from "react-i18next";
import { BoardSkeleton } from "@/components/skeletons";
import { GettingStartedChecklist } from "@/features/journey/GettingStartedChecklist";
import { JourneyRail } from "@/features/journey/JourneyRail";

import { ActionQueue } from "./ActionQueue";
import { AttentionCard } from "./AttentionCard";
import { DeskHealth } from "./DeskHealth";
import { InProgressCard } from "./InProgressCard";
import { RecentRuns } from "./RecentRuns";
import { QuickAccess } from "./QuickAccess";
import { StageRail } from "./StageRail";
import { UpcomingCard } from "./UpcomingCard";
import { useDashboardSummary } from "./use-dashboard-summary";

export function heroTitle(waiting: number): string {
  if (waiting === 0) return "Nothing is waiting on you";
  return `${waiting} job${waiting === 1 ? " is" : "s are"} waiting on you`;
}

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const { data: summary, isPending } = useDashboardSummary();
  if (isPending || !summary) return <BoardSkeleton />;

  const waiting = Object.values(summary.queues).reduce((a, b) => a + b, 0);
  // rejected is terminal-negative and never appears on the rail/queues (see
  // StageRail), so it must not count toward "the funnel has jobs in it".
  const totalJobs = Object.entries(summary.statusCounts).reduce(
    (sum, [status, count]) => (status === "rejected" ? sum : sum + count),
    0,
  );
  const eyebrow = `${t("dashboard.operations")} · ${new Date().toLocaleDateString(i18n.resolvedLanguage, {
    month: "short",
    day: "numeric",
  })}`;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        kicker={eyebrow}
        title={waiting === 0
          ? t("dashboard.waiting_zero", { count: waiting })
          : waiting === 1
            ? t("dashboard.waiting_one", { count: waiting })
            : t("dashboard.waiting_other", { count: waiting })}
        sub={t("dashboard.subtitle")}
      />
      <QuickAccess />
      <GettingStartedChecklist />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="stagger-children flex min-w-0 flex-col gap-6">
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
          <UpcomingCard events={summary.upcomingEvents ?? []} />
          <AttentionCard />
        </div>
        {/* Standing "is the desk working?" column: setup readiness plus live run
            activity. It is a landmark rather than a bare <div> so the grouping
            is nameable without a third uppercase heading competing with the two
            card titles already inside it.

            `self-start` is what makes `sticky` do anything here — a grid item
            defaults to `stretch`, so it would already be as tall as the row and
            have nothing to stick within. Status stays on screen while the work
            column scrolls; below xl the columns stack and status follows the
            work, which is the right priority order. */}
        <aside
          aria-label={t("dashboard.systemStatus")}
          className="stagger-children flex min-w-0 flex-col gap-6 xl:sticky xl:top-20 xl:self-start"
        >
          <DeskHealth />
          <RecentRuns />
        </aside>
      </div>
    </div>
  );
}
