import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { useRunStore } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";

type RunOut = { runId: string; kind: string };

const DEFAULT_INVALIDATE = ["shortlist", "pipeline", "triage", "job"];

function announceCompletion(run: import("@/lib/runs/store").RunRecord) {
  if (run.status === "failed") {
    toast.error(`${run.kind} failed: ${run.error ?? "unknown error"}`);
    return;
  }
  if (run.status === "cancelled") {
    toast.info(`${run.kind} cancelled`);
    return;
  }
  if (run.kind === "tailor") {
    const rawJobs = (run.result as { jobs?: unknown } | null)?.jobs;
    const jobs: unknown[] = Array.isArray(rawJobs) ? rawJobs : [];
    const versions = jobs.reduce<number>(
      (total, job) => {
        const count = (job as { versionCount?: unknown } | null)?.versionCount;
        return total + (typeof count === "number" ? count : 0);
      },
      0,
    );
    toast.success(
      `Tailoring complete: ${versions} resume versions created. Open a job's Versions tab to render PDF.`,
    );
    return;
  }
  toast.success(`${run.kind} completed`);
}

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
      trackRun({ runId: run.runId, kind }, (completed) => {
        invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
        announceCompletion(completed);
      });
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
  const current = useRunStore.getState().runs[runId];
  if (current) {
    useRunStore.getState().upsert({ ...current, status: "cancelling", phase: "Cancelling" });
  }
  try {
    await unwrap(
      api.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: runId } } }),
    );
  } catch (e) {
    if (current) useRunStore.getState().upsert(current);
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
  pullSources: (sourceIds: string[] | null, opts: PullOptions = {}) =>
    unwrap(api.POST("/api/pull", { body: { limit: opts.limit ?? null, sourceIds } })),
  discover: () => unwrap(api.POST("/api/discover", { body: {} })),
  reprocess: (scopes: ReprocessScope[]) =>
    unwrap(api.POST("/api/reprocess", { body: { scopes } })),
  refresh: (opts: PullOptions = {}) =>
    unwrap(api.POST("/api/refresh", { body: { limit: opts.limit ?? null } })),
  profileBuild: () => unwrap(api.POST("/api/profile/build", {} as never)),
  githubSync: () => unwrap(api.POST("/api/profile/sync-github", {} as never)),
};
