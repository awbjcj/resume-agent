import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { useRunStore } from "@/lib/runs/store";
import { cancelRun } from "./use-launch-run";
import type { RunRecord } from "@/lib/runs/store";

const STATUS_LABEL: Record<RunRecord["status"], string> = {
  queued: "queued",
  running: "",
  cancelling: "cancelling",
  succeeded: "done",
  failed: "failed",
  cancelled: "cancelled",
};

function rightLabel(r: RunRecord): string {
  if (r.status === "queued") return "queued";
  if (r.status === "succeeded") return "100% · done";
  if (r.status === "failed") return "failed";
  if (r.status === "cancelled") return `${Math.round(r.percent)}% · cancelled`;
  if (r.status === "cancelling") return `${Math.round(r.percent)}% · cancelling`;
  const eta = r.etaText ? ` · ~${r.etaText} left` : "";
  return `${Math.round(r.percent)}%${eta}`;
}

export function RunPanel() {
  // Select the stable map reference; deriving the array in a selector would
  // return a fresh array each render and trip React's useSyncExternalStore loop.
  const runsMap = useRunStore((s) => s.runs);
  const runs = Object.values(runsMap);
  if (runs.length === 0) return null;
  return (
    // aria-live announces run start/progress/completion to screen readers.
    <div aria-live="polite" className="border-b bg-card/55 px-5 py-3 md:px-8 lg:px-10">
      <div className="mx-auto w-full max-w-[1680px] space-y-2">
        {runs.map((r) => (
          <div key={r.runId} className="rounded-lg border bg-card p-3 shadow-sm">
            <div className="flex items-baseline justify-between gap-3 text-xs font-semibold uppercase tracking-[0.16em]">
              <span className="truncate">
                {r.kind}
                {r.phase ? ` · ${r.phase}` : ""}
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
                  {rightLabel(r)}
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
              aria-label={`${r.kind} progress ${STATUS_LABEL[r.status] || `${Math.round(r.percent)} percent`}`}
              className={`mt-1.5 h-1.5 ${
                r.status === "cancelled" || r.status === "cancelling" || r.status === "failed"
                  ? "opacity-50"
                  : ""
              }`}
            />
            {r.error && <p className="mt-1 text-xs text-destructive">{r.error}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
