import { useRunStore, type RunRecord } from "@/lib/runs/store";

const ACTIVE: RunRecord["status"][] = ["running", "cancelling", "queued"];

/**
 * The most relevant tracked run of the given kind: an in-flight one if present,
 * otherwise the most recently updated. Finished runs are never evicted from the
 * store, and singletons (e.g. profile-build) mint a fresh runId per submit once
 * the prior run completes — so a plain find-by-kind would return a stale run
 * (leaving "Rebuild" enabled and showing the old result during a new build).
 * Returns an existing store record (stable reference → no extra re-renders).
 */
export function useActiveRun(kind: string): RunRecord | undefined {
  return useRunStore((s) => {
    let best: RunRecord | undefined;
    for (const r of Object.values(s.runs)) {
      if (r.kind !== kind) continue;
      if (best === undefined) {
        best = r;
        continue;
      }
      const rActive = ACTIVE.includes(r.status);
      const bestActive = ACTIVE.includes(best.status);
      if (rActive !== bestActive) {
        if (rActive) best = r;
      } else if ((r.updatedAt ?? 0) > (best.updatedAt ?? 0)) {
        best = r;
      }
    }
    return best;
  });
}
