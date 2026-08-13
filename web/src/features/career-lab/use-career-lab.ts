import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, fetchAllPages, unwrap } from "@/lib/api/client";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { trackRun } from "@/lib/runs/tracker";
import type { components } from "@/lib/api/schema";

export type CareerLabSession = components["schemas"]["CareerLabSessionOut"];
export type CareerLabSessionSummary = components["schemas"]["CareerLabSessionSummaryOut"];
type CareerLabSessionsOut = components["schemas"]["CareerLabSessionsOut"];
export type CareerLabSkill = components["schemas"]["CareerLabSkillOut"];
export type CareerLabContext = components["schemas"]["CareerLabContextIn"];
export type CareerLabSkillName = components["schemas"]["CareerLabSkillName"];
export type CareerLabJob = components["schemas"]["PipelineItem"];
export type CareerLabJobDetail = components["schemas"]["JobDetail"];
type RunOut = components["schemas"]["RunOut"];
type StartInput = {
  message: string;
  goal?: string;
  skill?: CareerLabSkillName;
  context?: CareerLabContext;
};
type MessageInput = {
  sessionId: string;
  message: string;
  skill?: CareerLabSkillName;
  context?: CareerLabContext;
};

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
    meta: run.meta ?? null,
  });
  trackRun({ runId: run.runId, kind: run.kind }, onDone);
}

function useInvalidation() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["career-lab-sessions"] }),
      queryClient.invalidateQueries({ queryKey: ["career-lab-session"] }),
    ]);
  };
}

export function useCareerLabSkills() {
  return useQuery({
    queryKey: ["career-lab-skills"],
    queryFn: () =>
      unwrap(
        api.GET("/api/career-lab/skills"),
      ) as Promise<components["schemas"]["CareerLabSkillsOut"]>,
  });
}

/** Options rather than positionals: `includeArchived`, `page`, and `pageSize`
 *  are three same-typed knobs, so a transposed call would typecheck silently. */
export function useCareerLabSessions({
  includeArchived = false,
  page = 1,
  pageSize = 20,
  jobId,
}: {
  includeArchived?: boolean;
  page?: number;
  pageSize?: number;
  jobId?: number;
} = {}) {
  return useQuery({
    queryKey: ["career-lab-sessions", includeArchived, page, pageSize, jobId ?? null],
    queryFn: async () => {
      const fetchPage = (nextPage: number) =>
        api.GET("/api/career-lab/sessions", {
          params: {
            query: {
              includeArchived,
              page: nextPage,
              pageSize,
              ...(jobId != null ? { jobId } : {}),
            },
          },
        });
      const first = (await unwrap(fetchPage(page))) as CareerLabSessionsOut;
      if (page !== 1 || first.pagination.totalPages <= 1) return first;
      const allSessions = [...(first.sessions ?? [])];
      for (let nextPage = 2; nextPage <= first.pagination.totalPages; nextPage += 1) {
        const next = (await unwrap(fetchPage(nextPage))) as CareerLabSessionsOut;
        allSessions.push(...(next.sessions ?? []));
      }
      return { ...first, sessions: allSessions };
    },
  });
}

export function useCareerLabSession(sessionId: string | null) {
  return useQuery({
    queryKey: ["career-lab-session", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/career-lab/sessions/{session_id}", {
          params: { path: { session_id: sessionId as string } },
        }),
      ) as Promise<CareerLabSession>,
  });
}

export function useCareerLabJobs() {
  return useQuery({
    queryKey: ["career-lab-jobs"],
    queryFn: () =>
      fetchAllPages<CareerLabJob>((page) =>
        api.GET("/api/pipeline", {
          params: { query: { page, pageSize: 200, sortBy: "recency" } },
        }),
      ),
  });
}

export function useCareerLabJobDetail(jobId: number | null) {
  return useQuery({
    queryKey: ["career-lab-job", jobId],
    enabled: jobId != null,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId as number } },
        }),
      ) as Promise<CareerLabJobDetail>,
  });
}

function useRunMutation<T extends Record<string, unknown>>(
  launch: (input: T) => Promise<RunOut>,
) {
  const invalidate = useInvalidation();
  return useMutation({
    mutationFn: async (input: T & { onDone?: RunDone }) => {
      const run = await launch(input);
      seedRun(run, async (completed) => {
        await invalidate();
        if (completed.status !== "succeeded") {
          toast.error(completed.error ?? "Career Lab run did not complete");
        }
        input.onDone?.(completed);
      });
      return run;
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useStartCareerLab() {
  return useRunMutation<StartInput>(
    ({ message, goal, skill, context }) =>
      unwrap(
        api.POST("/api/career-lab/sessions", {
          body: { message: message ?? "", goal: goal ?? "", skill, context },
        }),
      ),
  );
}

export function useSendCareerLabMessage() {
  return useRunMutation<MessageInput>(
    ({ sessionId, message, skill, context }) =>
      unwrap(
        api.POST("/api/career-lab/sessions/{session_id}/messages", {
          params: { path: { session_id: sessionId } },
          body: { message, skill, context },
        }),
      ),
  );
}

export function useEndCareerLab() {
  return useRunMutation(({ sessionId }: { sessionId: string }) =>
    unwrap(
      api.POST("/api/career-lab/sessions/{session_id}/end", {
        params: { path: { session_id: sessionId } },
      }),
    ),
  );
}

export function useRenameCareerLabSession() {
  const invalidate = useInvalidation();
  return useMutation({
    mutationFn: ({ sessionId, title }: { sessionId: string; title: string }) =>
      unwrap(
        api.PATCH("/api/career-lab/sessions/{session_id}", {
          params: { path: { session_id: sessionId } },
          body: { title },
        }),
      ) as Promise<CareerLabSession>,
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}

function useLifecycleMutation(action: "archive" | "unarchive" | "delete") {
  const invalidate = useInvalidation();
  return useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) => {
      const params = { params: { path: { session_id: sessionId } } };
      if (action === "delete") return unwrap(api.DELETE("/api/career-lab/sessions/{session_id}", params));
      return unwrap(api.POST(`/api/career-lab/sessions/{session_id}/${action}`, params));
    },
    onSuccess: async () => {
      await invalidate();
      if (action === "delete") toast.success("Career Lab session deleted");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useArchiveCareerLabSession() { return useLifecycleMutation("archive"); }
export function useUnarchiveCareerLabSession() { return useLifecycleMutation("unarchive"); }
export function useDeleteCareerLabSession() { return useLifecycleMutation("delete"); }

export function useCareerLabRecoveredRun(sessionId: string | null): RunRecord | null {
  return useRunStore((state) => {
    const run = Object.values(state.runs).find(
      (candidate) =>
        candidate.kind.startsWith("career-lab") &&
        ["queued", "running", "cancelling"].includes(candidate.status) &&
        (sessionId
          ? candidate.meta?.sessionId === sessionId
          : // An un-anchored start: no session yet *and* no job. Without the
            // `jobId` test this also matched a start launched from a job
            // modal — same kind, same missing `sessionId` — so the page
            // adopted it and streamed a draft with no user turn.
            candidate.kind === "career-lab-turn"
            && !candidate.meta?.sessionId
            && !candidate.meta?.jobId),
    );
    return run ?? null;
  });
}
