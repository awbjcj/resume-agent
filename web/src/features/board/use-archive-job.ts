import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { invalidateBoardQueries } from "./query-invalidation";

function patchArchived(jobId: number, archived: boolean) {
  return unwrap(api.PATCH("/api/jobs/{job_id}", {
    params: { path: { job_id: jobId } },
    body: { archived },
  }));
}

export function useArchiveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, archived = true }: { jobId: number; archived?: boolean }) =>
      patchArchived(jobId, archived),
    onSuccess: async (_result, { jobId, archived = true }) => {
      await invalidateBoardQueries(queryClient);
      if (!archived) {
        toast.success("Job restored");
        return;
      }
      toast.success("Job archived", {
        action: {
          label: "Undo",
          onClick: () => {
            void patchArchived(jobId, false)
              .then(() => invalidateBoardQueries(queryClient))
              .then(() => toast.success("Job restored"))
              .catch((error: Error) => toast.error(`Restore failed: ${error.message}`));
          },
        },
      });
    },
    onError: (error) => toast.error(`Failed to update job: ${error.message}`),
  });
}
