import { useEffect } from "react";

import { pollRunsNow, startRunPoller, stopRunPoller } from "@/lib/runs/tracker";

/**
 * Recover in-flight and recently-finished runs on mount.
 *
 * The reconciliation pass itself lives in the tracker, so `/api/runs` has one
 * owner. This hook used to fetch that endpoint independently, which meant a
 * page load and a poll tick could disagree about what was running — and, worse,
 * that a run which finished while the client was away was announced by neither.
 */
export function useRehydrateRuns(): void {
  useEffect(() => {
    void pollRunsNow();
    startRunPoller();
    return () => stopRunPoller();
  }, []);
}
