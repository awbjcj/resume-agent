import { useQuery } from "@tanstack/react-query";

import { api, fetchAllPages } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type TriageItem = components["schemas"]["TriageItem"];

export function useTriage(archived: boolean) {
  return useQuery({
    queryKey: ["triage", archived],
    queryFn: (): Promise<TriageItem[]> =>
      fetchAllPages<TriageItem>((page) =>
        api.GET("/api/triage", { params: { query: { archived, pageSize: 200, page } } }),
      ),
  });
}
