import { useQuery } from "@tanstack/react-query";

import { useLaunchRun } from "@/features/runs/use-launch-run";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type MatchGap = components["schemas"]["MatchGapOut"];
export const MATCH_GAP_QUERY_KEY = ["match-gap"] as const;

export function useMatchGap() {
  return useQuery({
    queryKey: MATCH_GAP_QUERY_KEY,
    queryFn: (): Promise<MatchGap> => unwrap(api.GET("/api/match-gap", {})) as Promise<MatchGap>,
  });
}

export function useRefreshClusters() {
  const { launch } = useLaunchRun();
  const refresh = (skillKeys?: string[]) =>
    launch(
      "refreshClusters",
      () =>
        unwrap(
          api.POST(
            "/api/match-gap/refresh-clusters",
            skillKeys === undefined ? {} : { body: { skillKeys } },
          ),
        ),
      [...MATCH_GAP_QUERY_KEY],
    );

  return { refresh };
}

export function useMaintainTaxonomy() {
  const { launch } = useLaunchRun();
  const maintain = () =>
    launch(
      "maintainTaxonomy",
      () => unwrap(api.POST("/api/match-gap/maintain-taxonomy", {})),
      [...MATCH_GAP_QUERY_KEY],
    );
  return { maintain };
}

export function useUndoTaxonomyMaintenance() {
  const { launch } = useLaunchRun();
  const undo = () =>
    launch(
      "undoTaxonomyMaintenance",
      () => unwrap(api.POST("/api/match-gap/undo-taxonomy-maintenance", {})),
      [...MATCH_GAP_QUERY_KEY],
    );
  return { undo };
}
