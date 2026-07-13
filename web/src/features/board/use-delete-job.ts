import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { invalidateBoardQueries } from "./query-invalidation";

export function useDeleteJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) => unwrap(api.DELETE("/api/jobs/{job_id}", {
      params: { path: { job_id: jobId } },
    })),
    onSuccess: async () => {
      await invalidateBoardQueries(queryClient);
      toast.success("Job deleted");
    },
    onError: (error) => toast.error(error.message),
  });
}
