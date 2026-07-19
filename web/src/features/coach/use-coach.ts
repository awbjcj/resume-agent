import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";

export type CoachSession = components["schemas"]["CoachSessionOut"];
export type CoachSessionSummary = components["schemas"]["CoachSessionSummaryOut"];
export type CoachSessions = components["schemas"]["CoachSessionsOut"];
export type CoachDraftNote = components["schemas"]["CoachDraftNoteOut"];
export type CoachResearchAction = components["schemas"]["CoachResearchActionOut"];

type RunOut = components["schemas"]["RunOut"];
type RunDone = (run: RunRecord) => void;

function seedRun(run: RunOut, onDone?: RunDone): void {
  useRunStore.getState().upsert({
    runId: run.runId,
    kind: run.kind,
    status: "running",
    percent: run.percent,
    phase: run.label,
    current: run.current,
    total: run.total,
    etaText: run.etaText ?? null,
  });
  trackRun({ runId: run.runId, kind: run.kind }, onDone);
}

export function useCoachSessions(includeArchived = false) {
  return useQuery({
    queryKey: ["coach-sessions", includeArchived],
    queryFn: () =>
      unwrap(
        api.GET("/api/profile/coach/sessions", {
          params: {
            query: includeArchived ? { includeArchived: true } : {},
          },
        }),
      ) as Promise<CoachSessions>,
  });
}

function useCoachSessionInvalidation() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["coach-sessions"] }),
      queryClient.invalidateQueries({ queryKey: ["coach-session"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
    ]);
  };
}

function useCoachSessionMutation(action: "archive" | "unarchive" | "delete") {
  const invalidate = useCoachSessionInvalidation();
  return useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) => {
      const params = { params: { path: { session_id: sessionId } } };
      if (action === "delete") {
        return unwrap(
          api.DELETE("/api/profile/coach/sessions/{session_id}", params),
        );
      }
      return unwrap(
        api.POST(
          `/api/profile/coach/sessions/{session_id}/${action}`,
          params,
        ),
      );
    },
    onSuccess: async () => {
      await invalidate();
      if (action === "delete") toast.success("Coaching session deleted");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useArchiveCoachSession() {
  return useCoachSessionMutation("archive");
}

export function useUnarchiveCoachSession() {
  return useCoachSessionMutation("unarchive");
}

export function useDeleteCoachSession() {
  return useCoachSessionMutation("delete");
}

export function useCoachSession(sessionId: string | null) {
  return useQuery({
    queryKey: ["coach-session", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/profile/coach/sessions/{session_id}", {
          params: { path: { session_id: sessionId as string } },
        }),
      ) as Promise<CoachSession>,
  });
}

function useCoachRunMutation<T extends Record<string, unknown>>(
  launch: (input: T) => Promise<RunOut>,
  successMessage?: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: T & { onDone?: RunDone }) => {
      const run = await launch(input);
      seedRun(run, async (completed) => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["coach-sessions"] }),
          queryClient.invalidateQueries({ queryKey: ["coach-session"] }),
        ]);
        if (completed.status === "succeeded") {
          if (successMessage) toast.success(successMessage);
        } else {
          toast.error(completed.error ?? "Profile coach run did not complete");
        }
        input.onDone?.(completed);
      });
      return run;
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useStartCoachSession() {
  return useCoachRunMutation(() =>
    unwrap(api.POST("/api/profile/coach/sessions", {} as never)),
  );
}

export function useSendCoachMessage() {
  return useCoachRunMutation(
    ({ sessionId, message }: { sessionId: string; message: string }) =>
      unwrap(
        api.POST("/api/profile/coach/sessions/{session_id}/messages", {
          params: { path: { session_id: sessionId } },
          body: { message },
        }),
      ),
  );
}

export function useEndCoachSession() {
  const queryClient = useQueryClient();
  return useMutation({
        mutationFn: async ({
          sessionId,
          build,
          onDone,
        }: {
          sessionId: string;
          build: boolean;
          onDone?: RunDone;
        }) => {
          const run = await unwrap(
            api.POST("/api/profile/coach/sessions/{session_id}/end", {
              params: { path: { session_id: sessionId } },
              body: { build },
            }),
          );
          seedRun(run, async (completed) => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["coach-sessions"] }),
              queryClient.invalidateQueries({ queryKey: ["coach-session"] }),
            ]);
            const result = completed.result as { buildRunId?: string | null } | null;
            if (completed.status === "succeeded" && result?.buildRunId) {
              const buildRunId = result.buildRunId;
              seedRun(
                {
                  runId: buildRunId,
                  kind: "profile-build",
                  state: "pending",
                  label: "",
                  percent: 0,
                  current: 0,
                  total: 0,
                },
                async (buildRun) => {
                  await Promise.all([
                    queryClient.invalidateQueries({
                      queryKey: ["coach-session", sessionId],
                    }),
                    queryClient.invalidateQueries({ queryKey: ["coach-sessions"] }),
                    queryClient.invalidateQueries({ queryKey: ["setup-status"] }),
                    queryClient.invalidateQueries({ queryKey: ["profile-skeleton"] }),
                    queryClient.invalidateQueries({ queryKey: ["profile-matrix"] }),
                  ]);
                  if (buildRun.status === "succeeded") toast.success("Profile rebuild complete");
                  else toast.error(buildRun.error ?? "Profile rebuild failed");
                },
              );
            }
            if (completed.status === "succeeded") toast.success("Coaching session complete");
            else toast.error(completed.error ?? "Could not end coaching session");
            onDone?.(completed);
          });
          return run;
        },
        onError: (error: Error) => toast.error(error.message),
      });
}

export function useSaveCoachNote() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      topicId,
      title,
      summary,
      quotes,
    }: {
      sessionId: string;
      topicId: string;
      title: string;
      summary: string;
      quotes: string[];
    }) =>
      unwrap(
        api.POST("/api/profile/coach/sessions/{session_id}/notes/{topic_id}", {
          params: { path: { session_id: sessionId, topic_id: topicId } },
          body: { title, summary, quotes },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["coach-session"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-sessions"] }),
        queryClient.invalidateQueries({ queryKey: ["profile-sources"] }),
      ]);
      toast.success("Profile note saved");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDiscardCoachNote() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, topicId }: { sessionId: string; topicId: string }) =>
      unwrap(
        api.DELETE("/api/profile/coach/sessions/{session_id}/notes/{topic_id}", {
          params: { path: { session_id: sessionId, topic_id: topicId } },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["coach-session"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-sessions"] }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
