import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type DashboardSummary = components["schemas"]["DashboardSummaryOut"];

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: (): Promise<DashboardSummary> =>
      unwrap(api.GET("/api/dashboard/summary")),
  });
}
