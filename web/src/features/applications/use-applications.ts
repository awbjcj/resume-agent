import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ApplicationsTableData = components["schemas"]["PivotTableOut"];

export function useApplications() {
  return useQuery({
    queryKey: ["applications"],
    queryFn: (): Promise<ApplicationsTableData> => unwrap(api.GET("/api/applications")),
  });
}
