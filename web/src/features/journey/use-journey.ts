import { useMemo } from "react";

import { useDashboardSummary, type DashboardSummary } from "@/features/dashboard/use-dashboard-summary";
import { useSetupStatus, type SetupStatus } from "@/features/settings/use-setup-status";

/**
 * The single source of truth for the job-hunting arc. Both the persistent
 * JourneyRail and the first-run GettingStartedChecklist project this one model,
 * so they can never disagree about "what's next". The derivation is a pure
 * function of the two summaries the dashboard already loads — no extra network,
 * no backend work.
 */

export type JourneyStageId = "profile" | "sources" | "pull" | "shortlist" | "tailor";
export type JourneyStageState = "done" | "current" | "upcoming";

/** How a stage's call-to-action is fulfilled. `pull` opens the Pull dialog
 *  (reusing the real launcher); everything else navigates to a route. */
export type JourneyCta =
  | { readonly label: string; readonly to: string }
  | { readonly label: string; readonly pull: true };

interface JourneyStageDef {
  readonly id: JourneyStageId;
  /** Short noun for the rail node (e.g. "Profile"). */
  readonly label: string;
  /** Imperative phrasing for the checklist row (e.g. "Build your profile"). */
  readonly task: string;
  /** One line of what to do at this step, shown when it is the current step. */
  readonly hint: string;
  readonly cta: JourneyCta;
  readonly done: (s: SetupStatus, d: DashboardSummary) => boolean;
  /** Optional flavour count surfaced on the node / row. */
  readonly count?: (s: SetupStatus, d: DashboardSummary) => number;
}

export interface JourneyStage {
  readonly id: JourneyStageId;
  readonly label: string;
  readonly task: string;
  readonly hint: string;
  readonly cta: JourneyCta;
  readonly state: JourneyStageState;
  readonly count: number | null;
}

export interface Journey {
  readonly stages: readonly JourneyStage[];
  /** First stage not yet done, or null once every stage is complete. */
  readonly currentStep: JourneyStageId | null;
  readonly completedCount: number;
  readonly total: number;
  readonly complete: boolean;
}

/** Jobs that actually entered the funnel — rejected never appears on the
 *  rail/queues, so it must not count as "the funnel has jobs in it". */
function activeJobCount(d: DashboardSummary): number {
  return Object.entries(d.statusCounts).reduce(
    (sum, [status, count]) => (status === "rejected" ? sum : sum + count),
    0,
  );
}

const status = (d: DashboardSummary, key: string): number => d.statusCounts[key] ?? 0;

const pastShortlist = (d: DashboardSummary): number =>
  status(d, "shortlisted") + status(d, "approved") + status(d, "tailored") + status(d, "rendered");

export const JOURNEY_STAGES: readonly JourneyStageDef[] = [
  {
    id: "profile",
    label: "Profile",
    task: "Build your profile",
    hint: "Add your resume and build your profile so tailoring has facts to draw on.",
    cta: { label: "Build your profile", to: "/profile" },
    done: (s) => s.profile.hasResume && Boolean(s.profile.factsBuiltAt),
    count: (s) => s.profile.documentCount,
  },
  {
    id: "sources",
    label: "Sources",
    task: "Add job sources",
    hint: "Tell the agent where to look — set a search and enable at least one source.",
    cta: { label: "Add sources", to: "/settings/sources" },
    done: (s) => s.search.configured && s.sources.enabledCount > 0,
    count: (s) => s.sources.enabledCount,
  },
  {
    id: "pull",
    label: "Pull",
    task: "Pull your first jobs",
    hint: "Run your first pull to fill the funnel with fresh postings.",
    cta: { label: "Pull jobs", pull: true },
    done: (_s, d) => activeJobCount(d) > 0,
    count: (_s, d) => activeJobCount(d),
  },
  {
    id: "shortlist",
    label: "Shortlist",
    task: "Shortlist & approve",
    hint: "Review high-fit jobs and approve the ones worth tailoring.",
    cta: { label: "Review shortlist", to: "/shortlist" },
    done: (_s, d) => pastShortlist(d) > 0,
    count: (_s, d) => d.queues.approve ?? 0,
  },
  {
    id: "tailor",
    label: "Tailor",
    task: "Tailor a resume",
    hint: "Tailor a resume to an approved job, then render and apply.",
    cta: { label: "Tailor a resume", to: "/pipeline?stage=approved" },
    done: (_s, d) => status(d, "tailored") + status(d, "rendered") > 0,
    count: (_s, d) => d.queues.tailor ?? 0,
  },
];

/** Pure derivation — exported for unit tests and reused by the hook. */
export function deriveJourney(s: SetupStatus, d: DashboardSummary): Journey {
  const currentStep = JOURNEY_STAGES.find((stage) => !stage.done(s, d))?.id ?? null;
  let completedCount = 0;
  const stages = JOURNEY_STAGES.map((stage): JourneyStage => {
    const isDone = stage.done(s, d);
    if (isDone) completedCount += 1;
    const state: JourneyStageState = isDone
      ? "done"
      : stage.id === currentStep
        ? "current"
        : "upcoming";
    return {
      id: stage.id,
      label: stage.label,
      task: stage.task,
      hint: stage.hint,
      cta: stage.cta,
      state,
      count: stage.count ? stage.count(s, d) : null,
    };
  });
  return {
    stages,
    currentStep,
    completedCount,
    total: JOURNEY_STAGES.length,
    complete: currentStep === null,
  };
}

/** React hook: returns the derived journey, or null while either query loads. */
export function useJourney(): Journey | null {
  const setup = useSetupStatus();
  const summary = useDashboardSummary();
  const s = setup.data;
  const d = summary.data;
  return useMemo(() => (s && d ? deriveJourney(s, d) : null), [s, d]);
}
