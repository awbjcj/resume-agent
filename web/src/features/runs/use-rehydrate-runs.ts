import { useEffect } from "react";

import { api, fetchAllPages } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { stateToStatus } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";

type RunOut = components["schemas"]["RunOut"];

async function fetchActiveRuns(): Promise<RunOut[]> {
  const fetchPage = (page: number) =>
    api.GET("/api/runs", { params: { query: { page, pageSize: 200 } } });
  try {
    return await fetchAllPages<RunOut>(fetchPage);
  } catch {
    return fetchAllPages<RunOut>(fetchPage);
  }
}

export function useRehydrateRuns(): void {
  useEffect(() => {
    let cancelled = false;
    void fetchActiveRuns()
      .then((runs) => {
        if (cancelled) return;
        for (const run of runs) {
          useRunStore.getState().upsert({
            runId: run.runId,
            kind: run.kind,
            status: stateToStatus(run.state),
            percent: run.percent,
            phase: run.label,
            current: run.current,
            total: run.total,
            etaText: run.etaText ?? null,
            error: run.error ?? undefined,
            result: run.result as Record<string, unknown> | null,
            meta: (run.meta as Record<string, unknown> | null) ?? null,
          });
          if (["pending", "running", "cancelling"].includes(run.state)) {
            trackRun({ runId: run.runId, kind: run.kind });
          }
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
}
