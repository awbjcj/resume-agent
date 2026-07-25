import { api, unwrap } from "@/lib/api/client";

import { useLaunchRun } from "./use-launch-run";

export type RedoStage = "pull" | "extract" | "tailor" | "render";

export function useRedoRun() {
  const { launch } = useLaunchRun();
  return {
    redo: (jobIds: number[], stages: RedoStage[], deep: boolean) =>
      launch("redo", () =>
        unwrap(api.POST("/api/redo", { body: { jobIds, stages, deep } })),
      ),
  };
}
