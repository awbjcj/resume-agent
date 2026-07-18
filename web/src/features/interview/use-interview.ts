import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";

export type InterviewSession = components["schemas"]["InterviewSessionOut"];
export type InterviewSessionSummary =
  components["schemas"]["InterviewSessionSummaryOut"];
export type InterviewStyleIn = components["schemas"]["InterviewStyleIn"];
export type InterviewDebrief = components["schemas"]["InterviewDebriefOut"];

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

export function useInterviewSessions(jobId?: number) {
  return useQuery({
    queryKey: ["interview-sessions", jobId ?? null],
    queryFn: () =>
      unwrap(
        api.GET("/api/interview/sessions", {
          params: { query: jobId != null ? { jobId } : {} },
        }),
      ) as Promise<components["schemas"]["InterviewSessionsOut"]>,
  });
}

export function useInterviewSession(sessionId: string | null) {
  return useQuery({
    queryKey: ["interview-session", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/interview/sessions/{session_id}", {
          params: { path: { session_id: sessionId as string } },
        }),
      ) as Promise<InterviewSession>,
  });
}

function useInterviewRunMutation<T extends Record<string, unknown>>(
  launch: (input: T) => Promise<RunOut>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: T & { onDone?: RunDone }) => {
      const run = await launch(input);
      seedRun(run, async (completed) => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["interview-sessions"] }),
          queryClient.invalidateQueries({ queryKey: ["interview-session"] }),
        ]);
        if (completed.status !== "succeeded") {
          toast.error(completed.error ?? "Interview turn did not complete");
        }
        input.onDone?.(completed);
      });
      return run;
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useStartInterview() {
  return useInterviewRunMutation(
    ({
      jobId,
      resumeVersionId,
      style,
    }: {
      jobId: number;
      resumeVersionId: number;
      style: InterviewStyleIn;
    }) =>
      unwrap(
        api.POST("/api/interview/sessions", {
          body: { jobId, resumeVersionId, style },
        }),
      ),
  );
}

export function useSendInterviewAnswer() {
  return useInterviewRunMutation(
    ({ sessionId, message }: { sessionId: string; message: string }) =>
      unwrap(
        api.POST("/api/interview/sessions/{session_id}/messages", {
          params: { path: { session_id: sessionId } },
          body: { message },
        }),
      ),
  );
}

export function useEndInterview() {
  return useInterviewRunMutation(({ sessionId }: { sessionId: string }) =>
    unwrap(
      api.POST("/api/interview/sessions/{session_id}/end", {
        params: { path: { session_id: sessionId } },
      }),
    ),
  );
}
