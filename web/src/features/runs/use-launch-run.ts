import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { DEFAULT_INVALIDATE, rememberInvalidation } from "@/lib/runs/invalidation";
import { revisionMetaKey } from "@/lib/runs/revisions";
import { useRunStore } from "@/lib/runs/store";
import type { RunMeta } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";

type RunOut = { runId: string; kind: string; meta?: RunMeta | null };

function removeSupersededArtifactFailures(kind: string, meta?: RunMeta): void {
  const metaKey = revisionMetaKey(kind);
  if (!metaKey || meta?.[metaKey] == null) return;
  const store = useRunStore.getState();
  for (const run of Object.values(store.runs)) {
    if (
      run.kind === kind &&
      run.status === "failed" &&
      run.meta?.[metaKey] === meta[metaKey]
    ) {
      store.remove(run.runId);
    }
  }
}

export function useLaunchRun() {
  const launch = async (
    kind: string,
    call: () => Promise<unknown>,
    invalidate: string[] = [...DEFAULT_INVALIDATE],
    meta?: RunMeta,
  ): Promise<boolean> => {
    try {
      const run = (await call()) as RunOut;
      const effectiveMeta = run.meta ?? meta;
      removeSupersededArtifactFailures(kind, effectiveMeta);
      // The caller knows best which queries this particular run invalidates, so
      // it registers them against the run id. Announcing, acking and
      // invalidating then happen once, globally, in useRunCompletionEffects --
      // which is what lets a completion discovered on page load (with no launch
      // closure left alive) still refresh the board.
      rememberInvalidation(run.runId, invalidate);
      useRunStore.getState().upsert({
        runId: run.runId,
        kind,
        status: "running",
        percent: 0,
        phase: "",
        current: 0,
        total: 0,
        etaText: null,
        meta: effectiveMeta,
      });
      trackRun({ runId: run.runId, kind });
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
