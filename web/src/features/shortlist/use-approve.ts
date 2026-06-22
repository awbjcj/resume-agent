import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { ShortlistItem } from "@/lib/filters/types";

export function useApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { status: "approved" },
        }),
      ),
    onMutate: async (jobId) => {
      await qc.cancelQueries({ queryKey: ["shortlist"] });
      const prev = qc.getQueryData<ShortlistItem[]>(["shortlist"]);
      qc.setQueryData<ShortlistItem[]>(["shortlist"], (old) =>
        old?.filter((r) => r.jobId !== jobId),
      );
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(["shortlist"], ctx.prev);
      toast.error("Failed to approve job");
    },
    onSuccess: () => toast.success("Approved for tailoring"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["shortlist"] }),
  });
}
