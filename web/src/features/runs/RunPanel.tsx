import { Progress } from "@/components/ui/progress";
import { useRunStore } from "@/lib/runs/store";

export function RunPanel() {
  // Select the stable map reference; deriving the array in a selector would
  // return a fresh array each render and trip React's useSyncExternalStore loop.
  const runsMap = useRunStore((s) => s.runs);
  const runs = Object.values(runsMap);
  if (runs.length === 0) return null;
  return (
    // aria-live announces run start/progress/completion to screen readers.
    <div aria-live="polite" className="space-y-2 border-b px-6 py-3">
      {runs.map((r) => (
        <div key={r.runId} className="rounded-lg border bg-card p-2">
          <div className="flex items-baseline justify-between font-mono text-xs uppercase tracking-widest">
            <span>
              {r.kind}
              {r.phase ? ` · ${r.phase}` : ""}
            </span>
            <span>{r.status === "failed" ? "failed" : `${Math.round(r.percent)}%`}</span>
          </div>
          <Progress
            value={Math.round(r.percent)}
            aria-label={`${r.kind} progress`}
            className="mt-1 h-1.5"
          />
          {r.error && <p className="mt-1 text-xs text-destructive">{r.error}</p>}
        </div>
      ))}
    </div>
  );
}
