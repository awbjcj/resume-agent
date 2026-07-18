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
  const refresh = () =>
    launch(
      "refreshClusters",
      () => unwrap(api.POST("/api/match-gap/refresh-clusters", {})),
      [...MATCH_GAP_QUERY_KEY],
    );

  return { refresh };
}
