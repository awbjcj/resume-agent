import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ApplicationEvent = components["schemas"]["ApplicationEventOut"];
export type ApplicationEventCreate = components["schemas"]["ApplicationEventCreate"];
export type ApplicationEventUpdate = components["schemas"]["ApplicationEventUpdate"];

const key = (jobId: number) => ["application-events", jobId] as const;

function useInvalidateApplicationEvents(jobId: number) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: key(jobId) });
    queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
    queryClient.invalidateQueries({ queryKey: ["analytics-timeline"] });
  };
}

export function useApplicationEvents(jobId: number) {
  return useQuery({
    queryKey: key(jobId),
    queryFn: (): Promise<ApplicationEvent[]> =>
      unwrap(
        api.GET("/api/jobs/{job_id}/events", {
          params: { path: { job_id: jobId } },
        }),
      ),
  });
}

export function useCreateEvent(jobId: number) {
  const invalidate = useInvalidateApplicationEvents(jobId);
  return useMutation({
    mutationFn: (body: ApplicationEventCreate) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/events", {
          params: { path: { job_id: jobId } },
          body,
        }),
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Event added");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useUpdateEvent(jobId: number, eventId: number) {
  const invalidate = useInvalidateApplicationEvents(jobId);
  return useMutation({
    mutationFn: (body: ApplicationEventUpdate) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}/events/{event_id}", {
          params: { path: { job_id: jobId, event_id: eventId } },
          body,
        }),
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Event updated");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDeleteEvent(jobId: number, eventId: number) {
  const invalidate = useInvalidateApplicationEvents(jobId);
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/jobs/{job_id}/events/{event_id}", {
          params: { path: { job_id: jobId, event_id: eventId } },
        }),
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Event removed");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
