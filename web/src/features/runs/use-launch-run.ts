import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";

type RunOut = { runId: string; kind: string };

const DEFAULT_INVALIDATE = ["shortlist", "pipeline", "triage"];

export function useLaunchRun() {
  const qc = useQueryClient();
  const launch = async (
    kind: string,
    call: () => Promise<unknown>,
    invalidate: string[] = DEFAULT_INVALIDATE,
  ): Promise<boolean> => {
    try {
      const run = (await call()) as RunOut;
      useRunStore.getState().upsert({
        runId: run.runId,
        kind,
        status: "running",
        percent: 0,
        phase: "",
        current: 0,
        total: 0,
        etaText: null,
      });
      watchRun(run.runId, kind, () =>
        invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
      );
      return true;
    } catch (e) {
      toast.error(`Failed to start ${kind}: ${(e as Error).message}`);
      return false;
    }
  };
  return { launch };
}

/** Request cooperative cancellation of a running operation. */
export async function cancelRun(runId: string): Promise<void> {
  try {
    await unwrap(
      api.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: runId } } }),
    );
  } catch (e) {
    toast.error(`Couldn't cancel run: ${(e as Error).message}`);
  }
}

export interface PullOptions {
  limit?: number | null;
}

export type ReprocessScope =
  | "shortlisted"
  | "rejected:relevance"
  | "rejected:filtered"
  | "all";

export const launchers = {
  pull: (opts: PullOptions = {}) =>
    unwrap(api.POST("/api/pull", { body: { limit: opts.limit ?? null } })),
  discover: () => unwrap(api.POST("/api/discover", { body: {} })),
  reprocess: (scopes: ReprocessScope[]) =>
    unwrap(api.POST("/api/reprocess", { body: { scopes } })),
  refresh: (opts: PullOptions = {}) =>
    unwrap(api.POST("/api/refresh", { body: { limit: opts.limit ?? null } })),
};
