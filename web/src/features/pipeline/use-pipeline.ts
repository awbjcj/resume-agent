import { useQuery } from "@tanstack/react-query";

import { api, fetchAllPages } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type PipelineItem = components["schemas"]["PipelineItem"];

export function usePipeline() {
  return useQuery({
    queryKey: ["pipeline"],
    queryFn: (): Promise<PipelineItem[]> =>
      fetchAllPages<PipelineItem>((page) =>
        api.GET("/api/pipeline", { params: { query: { pageSize: 200, page } } }),
      ),
  });
}
