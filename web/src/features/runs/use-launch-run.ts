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
  ) => {
    try {
      const run = (await call()) as RunOut;
      useRunStore
        .getState()
        .upsert({ runId: run.runId, kind, status: "running", percent: 0, phase: "" });
      watchRun(run.runId, kind, () =>
        invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
      );
    } catch (e) {
      toast.error(`Failed to start ${kind}: ${(e as Error).message}`);
    }
  };
  return { launch };
}

export const launchers = {
  pull: () => unwrap(api.POST("/api/pull", { body: {} })),
  discover: () => unwrap(api.POST("/api/discover", {})),
};
