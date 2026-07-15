import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";

export type InterviewHistory = components["schemas"]["InterviewHistoryOut"];
export type InterviewAnswers = components["schemas"]["InterviewAnswersIn"];

export type InterviewRound = {
  roundId: string;
  questions: Array<{
    id: string;
    gap: string;
    whyItMatters: string;
    questionText: string;
    relatedRef: string;
  }>;
  researchActions: Array<{
    kind: "harvest_repo" | "request_url";
    target: string;
    why: string;
  }>;
};

export function useInterviewHistory() {
  return useQuery({
    queryKey: ["profile-interview-history"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/interview/history", {} as never)) as Promise<InterviewHistory>,
  });
}

export function useStartInterview() {
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/profile/interview", {} as never)) as Promise<{
        runId: string;
      }>,
    onError: (error: Error) => toast.error(error.message),
  });
}

type Completion = {
  runId: string;
  state: "done" | "error";
  round: InterviewRound | null;
  error: string | null;
};

export function useInterviewRound(runId: string | null) {
  const [completion, setCompletion] = useState<Completion | null>(null);

  useEffect(() => {
    if (!runId) return;
    trackRun({ runId, kind: "profile-interview" }, (run: RunRecord) => {
      if (run.status === "succeeded") {
        setCompletion({
          runId,
          state: "done",
          round: run.result as InterviewRound,
          error: null,
        });
      } else {
        setCompletion({
          runId,
          state: "error",
          round: null,
          error:
            run.error ??
            (run.status === "cancelled" ? "Interview cancelled" : "Interview failed"),
        });
      }
    });
  }, [runId]);

  if (!runId) return { state: "idle" as const, round: null, error: null };
  if (!completion || completion.runId !== runId) {
    return { state: "running" as const, round: null, error: null };
  }
  return completion;
}

export function useSubmitInterview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, ...body }: InterviewAnswers & { runId: string }) =>
      unwrap(
        api.POST("/api/profile/interview/{run_id}/answers", {
          params: { path: { run_id: runId } },
          body,
        }),
      ),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["profile-interview-history"] }),
        queryClient.invalidateQueries({ queryKey: ["profile-sources"] }),
        queryClient.invalidateQueries({ queryKey: ["setup-status"] }),
      ]);
      if (result.buildStarted && result.buildRunId) {
        useRunStore.getState().upsert({
          runId: result.buildRunId,
          kind: "profile-build",
          status: "running",
          percent: 0,
          phase: "",
          current: 0,
          total: 0,
          etaText: null,
        });
        trackRun(
          { runId: result.buildRunId, kind: "profile-build" },
          async (completed) => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["setup-status"] }),
              queryClient.invalidateQueries({ queryKey: ["profile-skeleton"] }),
              queryClient.invalidateQueries({ queryKey: ["profile-matrix"] }),
            ]);
            if (completed.status === "succeeded") {
              toast.success("Profile rebuild complete");
            } else if (completed.status === "failed") {
              toast.error(completed.error ?? "Profile rebuild failed");
            }
          },
        );
        toast.success("Answers saved; profile rebuild started");
      } else {
        toast.success("Answers saved");
      }
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
