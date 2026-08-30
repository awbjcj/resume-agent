import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { useTranslation } from "react-i18next";
import { localizeRunError, localizeRunEta, localizeRunKind, localizeRunPhase, localizeRunStatus } from "@/i18n/dynamic-labels";
import { useRunStore } from "@/lib/runs/store";
import { cancelRun } from "./use-launch-run";
import type { RunRecord } from "@/lib/runs/store";

function rightLabel(r: RunRecord, language: string | undefined): string {
  if (r.status === "queued") return localizeRunStatus(r.status, language);
  if (r.status === "succeeded") return `100% · ${localizeRunStatus(r.status, language)}`;
  if (r.status === "failed") return localizeRunStatus(r.status, language);
  if (r.status === "cancelled") return `${Math.round(r.percent)}% · ${localizeRunStatus(r.status, language)}`;
  if (r.status === "cancelling") return `${Math.round(r.percent)}% · ${localizeRunStatus(r.status, language)}`;
  const etaText = localizeRunEta(r.etaText, language);
  return `${Math.round(r.percent)}%${etaText ? ` · ${etaText}` : ""}`;
}

export function RunPanel() {
  const { t, i18n } = useTranslation();
  // Select the stable map reference; deriving the array in a selector would
  // return a fresh array each render and trip React's useSyncExternalStore loop.
  const runsMap = useRunStore((s) => s.runs);
  const runs = Object.values(runsMap);
  if (runs.length === 0) return null;
  return (
    // aria-live announces run start/progress/completion to screen readers.
    <div aria-live="polite" className="border-b bg-card/55 px-5 py-3 md:px-8 lg:px-10">
      <div className="mx-auto w-full max-w-[1680px] space-y-2">
        {runs.map((r) => {
          const kind = localizeRunKind(r.kind, i18n.resolvedLanguage, t);
          const phase = localizeRunPhase(r.phase, i18n.resolvedLanguage);
          const error = localizeRunError(r.error, i18n.resolvedLanguage);
          return (
          <div key={r.runId} className="rounded-lg border bg-card p-3 shadow-sm">
            <div className="flex items-baseline justify-between gap-3 text-xs font-semibold uppercase tracking-[0.16em]">
              <span className="truncate">
                {kind}
                {phase ? ` · ${phase}` : ""}
                {r.total > 0 && r.status === "running" && (
                  <span className="ml-1.5 tabular-nums text-muted-foreground normal-case">
                    {r.current}/{r.total}
                  </span>
                )}
              </span>
              <div className="flex shrink-0 items-center gap-3">
                <span
                  className={`tabular-nums ${
                    r.status === "failed"
                      ? "text-destructive"
                      : r.status === "cancelled" || r.status === "cancelling"
                        ? "text-muted-foreground"
                        : ""
                  }`}
                >
                  {rightLabel(r, i18n.resolvedLanguage)}
                </span>
                {r.status === "running" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-[0.68rem] font-semibold uppercase tracking-[0.12em]"
                    onClick={() => cancelRun(r.runId)}
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>
            <Progress
              value={Math.round(r.percent)}
              aria-label={t("runPanel.progress", {
                kind,
                status: r.status === "running" ? `${Math.round(r.percent)}%` : localizeRunStatus(r.status, i18n.resolvedLanguage),
              })}
              className={`mt-1.5 h-1.5 ${
                r.status === "cancelled" || r.status === "cancelling" || r.status === "failed"
                  ? "opacity-50"
                  : ""
              }`}
            />
            {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
          </div>
          );
        })}
      </div>
    </div>
  );
}
