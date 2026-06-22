import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";

function invalidateBoards(qc: ReturnType<typeof useQueryClient>) {
  for (const k of ["triage", "pipeline", "shortlist"]) {
    qc.invalidateQueries({ queryKey: [k] });
  }
}

export function useArchive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { archived: true },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: ["triage"] }),
  });
}

export function useRestore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { archived: false },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: ["triage"] }),
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(api.DELETE("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } })),
    onError: () => toast.error("Job has progress and cannot be deleted"),
    // Delete is reachable from the drawer over any board, so refresh all.
    onSettled: () => invalidateBoards(qc),
  });
}
