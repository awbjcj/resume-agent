import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type Analytics = components["schemas"]["AnalyticsOut"];

export function useAnalytics() {
  return useQuery({
    queryKey: ["analytics"],
    queryFn: (): Promise<Analytics> => unwrap(api.GET("/api/analytics", {})) as Promise<Analytics>,
  });
}
