import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type TriageItem = components["schemas"]["TriageItem"];

export function useTriage(archived: boolean) {
  return useQuery({
    queryKey: ["triage", archived],
    queryFn: async (): Promise<TriageItem[]> => {
      const page = await unwrap(
        api.GET("/api/triage", { params: { query: { archived, pageSize: 200 } } }),
      );
      return (page as { data: TriageItem[] }).data;
    },
  });
}
