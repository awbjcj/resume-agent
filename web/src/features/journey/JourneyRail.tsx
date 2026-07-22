import { Link } from "react-router-dom";
import { ArrowRight, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { PullDialog } from "@/features/runs/RunLaunchDialogs";
import { cn } from "@/lib/utils";

import { useJourney, type JourneyCta, type JourneyStage } from "./use-journey";

/** Renders a stage's call-to-action: the Pull step reuses the real launcher
 *  dialog; every other step is a route link. */
function StageAction({ cta }: { cta: JourneyCta }) {
  if ("pull" in cta) return <PullDialog />;
  return (
    <Button size="sm" render={<Link to={cta.to}>{cta.label}</Link>} />
  );
}

function Node({
  stage,
  index,
  connectorDone,
}: {
  stage: JourneyStage;
  index: number;
  connectorDone: boolean;
}) {
  const isDone = stage.state === "done";
  const isCurrent = stage.state === "current";
  return (
    <li
      aria-current={isCurrent ? "step" : undefined}
      className="flex min-w-0 flex-1 items-start"
    >
      {index > 0 && (
        <span
          aria-hidden="true"
          className={cn("mx-1 mt-4 h-px flex-1 sm:mx-2", connectorDone ? "bg-primary" : "bg-border")}
        />
      )}
      <span
        className={cn(
          "flex min-w-0 flex-1 flex-col items-center gap-2 text-center",
          stage.state === "upcoming" && "opacity-45",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "flex size-9 items-center justify-center rounded-full border text-sm font-semibold tabular-nums transition-colors",
            isDone && "border-primary bg-primary text-primary-foreground",
            isCurrent && "border-primary text-primary ring-4 ring-primary/15",
            stage.state === "upcoming" && "border-border text-muted-foreground",
          )}
        >
          {isDone ? <Check className="size-4" /> : index + 1}
        </span>
        <span className="flex flex-col gap-0.5">
          <span className={cn("text-xs font-semibold", isCurrent ? "text-foreground" : "text-muted-foreground")}>
            {stage.label}
          </span>
          {isCurrent && stage.count != null && stage.count > 0 && (
            <span className="text-[0.68rem] tabular-nums text-muted-foreground">{stage.count} waiting</span>
          )}
        </span>
      </span>
    </li>
  );
}

export function JourneyRail() {
  const journey = useJourney();
  if (!journey) return null;

  // Once the loop is running, the rail recedes to a single quiet orientation
  // line — still present, but no longer demanding action.
  if (journey.complete) {
    return (
      <div
        aria-label="Job-search journey"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm"
      >
        <span className="flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Check className="size-3" aria-hidden="true" />
        </span>
        <span className="font-medium text-foreground">You&apos;re running the full loop.</span>
        <span>Profile · Sources · Pull · Shortlist · Tailor — all set.</span>
      </div>
    );
  }

  const current = journey.stages.find((s) => s.state === "current");

  return (
    <section aria-label="Job-search journey" className="rounded-xl border bg-card p-4 shadow-sm sm:p-5">
      <ol className="flex items-start">
        {journey.stages.map((stage, i) => (
          <Node
            key={stage.id}
            stage={stage}
            index={i}
            connectorDone={i > 0 && journey.stages[i - 1].state === "done"}
          />
        ))}
      </ol>
      {current && (
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-4">
          <ArrowRight className="size-4 shrink-0 text-primary" aria-hidden="true" />
          <p className="min-w-0 flex-1 text-sm text-foreground">
            <span className="font-medium">Next:</span> {current.hint}
          </p>
          <StageAction cta={current.cta} />
        </div>
      )}
    </section>
  );
}
