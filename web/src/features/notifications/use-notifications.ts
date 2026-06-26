import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";
import type { components } from "@/lib/api/schema";

export type NotificationItem = components["schemas"]["NotificationOut"];
type RunOut = components["schemas"]["RunOut"];
const KEY = ["notifications"];

export function useNotifications() {
  return useQuery<NotificationItem[]>({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET("/api/notifications")),
  });
}

export function useAcceptNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST("/api/notifications/{notification_id}/accept", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDismissNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST("/api/notifications/{notification_id}/dismiss", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useGmailSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (): Promise<RunOut> => unwrap(api.POST("/api/gmail/sync")),
    onSuccess: (run) => {
      useRunStore.getState().upsert({
        runId: run.runId,
        kind: "gmailSync",
        status: "running",
        percent: 0,
        phase: "",
        current: 0,
        total: 0,
        etaText: null,
      });
      watchRun(run.runId, "gmailSync", () =>
        qc.invalidateQueries({ queryKey: KEY }),
      );
    },
  });
}
