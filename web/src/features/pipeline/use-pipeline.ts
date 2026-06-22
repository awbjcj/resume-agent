import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type PipelineItem = components["schemas"]["PipelineItem"];

export function usePipeline() {
  return useQuery({
    queryKey: ["pipeline"],
    queryFn: async (): Promise<PipelineItem[]> => {
      const page = await unwrap(
        api.GET("/api/pipeline", { params: { query: { pageSize: 200 } } }),
      );
      return (page as { data: PipelineItem[] }).data;
    },
  });
}
