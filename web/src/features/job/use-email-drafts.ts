import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import type { components } from "@/lib/api/schema";

export type EmailDraft = components["schemas"]["EmailDraftOut"];
type RunOut = components["schemas"]["RunOut"];

const key = (jobId: number) => ["email-drafts", jobId];

export function useEmailDrafts(jobId: number, enabled = true) {
  return useQuery<EmailDraft[]>({
    queryKey: key(jobId),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/email-drafts", {
          params: { path: { job_id: jobId } },
        }),
      ),
  });
}

export function useGenerateEmailDraft(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      draftType: string;
      instructions?: string;
    }): Promise<RunOut> =>
      unwrap(
        api.POST("/api/jobs/{job_id}/email-draft", {
          params: { path: { job_id: jobId } },
          body,
        }),
      ),
    onSuccess: (run) => {
      watchRun(run.runId, "emailDraft", () =>
        qc.invalidateQueries({ queryKey: key(jobId) }),
      );
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useSaveEmailDraft(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draftId: number) =>
      unwrap(
        api.POST("/api/email-drafts/{draft_id}/save", {
          params: { path: { draft_id: draftId } },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key(jobId) });
      toast.success("Saved to Gmail drafts");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
