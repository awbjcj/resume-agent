import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ErrorRecord = components["schemas"]["ErrorRecordOut"];

// AttentionCard has no pagination UI -- it presents "every open error" behind
// a local Show all toggle, so this requests the backend's own page-size
// ceiling (api/routers/errors.py::MAX_PAGE_SIZE) rather than its 50-row
// default page.
const MAX_PAGE_SIZE = 200;

export function useErrorRecords(
  status: "open" | "dismissed" | "resolved" = "open",
) {
  return useQuery({
    queryKey: ["error-records", status],
    queryFn: () =>
      unwrap(
        api.GET("/api/errors", {
          params: { query: { status, pageSize: MAX_PAGE_SIZE } },
        }),
      ) as Promise<components["schemas"]["ErrorRecordsOut"]>,
  });
}

function useErrorInvalidation() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["error-records"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
    ]);
  };
}

function useErrorMutation(action: "dismiss" | "resolve") {
  const invalidate = useErrorInvalidation();
  return useMutation({
    mutationFn: ({ id }: { id: number }) =>
      unwrap(
        api.POST(`/api/errors/{record_id}/${action}`, {
          params: { path: { record_id: id } },
        }),
      ),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDismissError() {
  return useErrorMutation("dismiss");
}

export function useResolveError() {
  return useErrorMutation("resolve");
}

export function useDismissAllErrors() {
  const invalidate = useErrorInvalidation();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/errors/dismiss-all", {})),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}
