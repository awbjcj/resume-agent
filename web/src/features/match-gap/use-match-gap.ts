import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type MatchGap = components["schemas"]["MatchGapOut"];

export function useMatchGap() {
  return useQuery({
    queryKey: ["match-gap"],
    queryFn: (): Promise<MatchGap> => unwrap(api.GET("/api/match-gap", {})) as Promise<MatchGap>,
  });
}
