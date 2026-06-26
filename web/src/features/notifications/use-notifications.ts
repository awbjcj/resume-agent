import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";
import type { components } from "@/lib/api/schema";

export type NotificationItem = {
  id: number;
  applicationId: number;
  kind: string;
  proposedStatus: string;
  evidence: string;
  messageId: string;
  state: string;
  createdAt: string;
};

type RunOut = components["schemas"]["RunOut"];
const KEY = ["notifications"];

function getUntyped<T>(path: string): Promise<T> {
  const get = api.GET as (path: string) => Promise<{ data?: T; error?: unknown }>;
  return unwrap(get(path));
}

function postUntyped<T>(path: string, options?: unknown): Promise<T> {
  const post = api.POST as (
    path: string,
    options?: unknown,
  ) => Promise<{ data?: T; error?: unknown }>;
  return unwrap(post(path, options));
}

export function useNotifications() {
  return useQuery<NotificationItem[]>({
    queryKey: KEY,
    queryFn: () => getUntyped("/api/notifications"),
  });
}

export function useAcceptNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      postUntyped("/api/notifications/{notification_id}/accept", {
        params: { path: { notification_id: id } },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDismissNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      postUntyped("/api/notifications/{notification_id}/dismiss", {
        params: { path: { notification_id: id } },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useGmailSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => postUntyped<RunOut>("/api/gmail/sync"),
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
