import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslation } from "react-i18next";
import { Progress } from "@/components/ui/progress";
import { localizeRunKind, localizeRunPhase } from "@/i18n/dynamic-labels";
import { useRunStore, type RunRecord } from "@/lib/runs/store";

import { timeAgo } from "./time-ago";

const ACTIVE: RunRecord["status"][] = ["running", "cancelling", "queued"];

const OUTCOME: Partial<Record<RunRecord["status"], string>> = {
  succeeded: "done",
  failed: "failed",
  cancelled: "cancelled",
};

function order(a: RunRecord, b: RunRecord): number {
  const activeDelta =
    Number(ACTIVE.includes(b.status)) - Number(ACTIVE.includes(a.status));
  return activeDelta || (b.updatedAt ?? 0) - (a.updatedAt ?? 0);
}

export function RecentRuns() {
  const { t, i18n } = useTranslation();
  const [now] = useState(Date.now);
  // Select the stable map reference (same reasoning as RunPanel): deriving the
  // array inside the selector would return a fresh array every render.
  const runsMap = useRunStore((s) => s.runs);
  const runs = Object.values(runsMap).sort(order).slice(0, 5);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {t("dashboard.recentRuns")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("dashboard.noRuns")}
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {runs.map((run) => {
              const kind = localizeRunKind(run.kind, i18n.resolvedLanguage, t);
              const phase = localizeRunPhase(run.phase, i18n.resolvedLanguage);
              return (
              <li key={run.runId} className="min-w-0">
                <div className="flex items-baseline justify-between gap-3 text-xs font-semibold uppercase tracking-[0.14em]">
                  <span className="truncate">
                    {kind}
                    {phase ? ` · ${phase}` : ""}
                  </span>
                  <span
                    className={`shrink-0 tabular-nums ${
                      run.status === "failed"
                        ? "text-destructive"
                        : "text-muted-foreground"
                    }`}
                  >
                    {ACTIVE.includes(run.status)
                      ? `${Math.round(run.percent)}%`
                      : `${run.status === "succeeded"
                          ? t("dashboard.outcomes.done")
                          : run.status === "failed"
                            ? t("dashboard.outcomes.failed")
                            : run.status === "cancelled"
                              ? t("dashboard.outcomes.cancelled")
                              : OUTCOME[run.status] ?? run.status}${
                          run.updatedAt ? ` · ${timeAgo(run.updatedAt, now, i18n.resolvedLanguage)}` : ""
                        }`}
                  </span>
                </div>
                {ACTIVE.includes(run.status) && (
                  <Progress
                    value={Math.round(run.percent)}
                    aria-label={t("dashboard.runProgress", { kind })}
                    className="mt-1.5 h-1.5"
                  />
                )}
              </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
