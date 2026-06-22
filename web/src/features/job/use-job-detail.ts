import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type JobDetail = components["schemas"]["JobDetail"];

export function useJobDetail(jobId: number) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: (): Promise<JobDetail> =>
      unwrap(
        api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } }),
      ) as Promise<JobDetail>,
  });
}
