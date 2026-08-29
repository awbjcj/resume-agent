import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PullDialog } from "@/features/runs/RunLaunchDialogs";
import { cn } from "@/lib/utils";

import { useJourney, type JourneyCta, type JourneyStage } from "./use-journey";

const DISMISS_KEY = "resume-agent-getting-started-dismissed";

function RowAction({ cta }: { cta: JourneyCta }) {
  if ("pull" in cta) return <PullDialog triggerLabel={cta.label} />;
  return (
    <Button size="sm" variant="outline" render={<Link to={cta.to}>{cta.label}</Link>} />
  );
}

function Row({ stage, index }: { stage: JourneyStage; index: number }) {
  const isDone = stage.state === "done";
  const isCurrent = stage.state === "current";
  return (
    <li
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2.5",
        isCurrent && "bg-primary/8 ring-1 ring-primary/20",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
          isDone && "border-primary bg-primary text-primary-foreground",
          isCurrent && "border-primary text-primary",
          stage.state === "upcoming" && "border-border text-muted-foreground",
        )}
      >
        {isDone ? <Check className="size-3.5" /> : index + 1}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn(
            "text-sm font-medium",
            isDone && "text-muted-foreground line-through",
            !isDone && !isCurrent && "text-muted-foreground",
          )}
        >
          {stage.task}
        </span>
        {isCurrent && <span className="text-xs text-muted-foreground">{stage.hint}</span>}
      </span>
      {isCurrent && <RowAction cta={stage.cta} />}
    </li>
  );
}

export function GettingStartedChecklist() {
  const { t } = useTranslation();
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISS_KEY) === "1",
  );
  const journey = useJourney();

  // Auto-hide once the loop is complete, if dismissed, or while loading.
  if (!journey || journey.complete || dismissed) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  };

  return (
    <Card className="gap-0 p-0">
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <h2 className="text-sm font-semibold">{t("journey.gettingStarted")}</h2>
        <span className="text-xs tabular-nums text-muted-foreground">
          {t("journey.completedCount", {
            completed: journey.completedCount,
            total: journey.total,
          })}
        </span>
        <Button
          size="icon-sm"
          variant="ghost"
          className="ml-auto"
          onClick={dismiss}
          aria-label={t("journey.dismiss")}
        >
          <X className="size-4" aria-hidden="true" />
        </Button>
      </div>
      <ol className="flex flex-col gap-0.5 p-2">
        {journey.stages.map((stage, i) => (
          <Row key={stage.id} stage={stage} index={i} />
        ))}
      </ol>
    </Card>
  );
}
