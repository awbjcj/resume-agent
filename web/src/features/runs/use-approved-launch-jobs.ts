import { useQuery } from "@tanstack/react-query";

import { api, fetchAllPages } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import type { LaunchJob } from "./LaunchDialog";

type PipelineItem = components["schemas"]["PipelineItem"];

export function useApprovedLaunchJobs(enabled: boolean) {
  const query = useQuery({
    queryKey: ["launch-jobs", "approved"],
    enabled,
    queryFn: () =>
      fetchAllPages<PipelineItem>((page) =>
        api.GET("/api/pipeline", {
          params: {
            query: {
              status: "approved",
              sortBy: "recency",
              page,
              pageSize: 200,
            },
          },
        }),
      ),
  });

  return {
    jobs: (query.data ?? []).map<LaunchJob>((job) => ({
      jobId: job.jobId,
      company: job.company,
      title: job.title,
    })),
    isLoading: query.isPending && enabled,
    error: query.error instanceof Error ? query.error.message : null,
    retry: query.refetch,
  };
}
