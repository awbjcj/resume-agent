import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "@/features/runs/use-launch-run";

function invalidateBoards(qc: ReturnType<typeof useQueryClient>, jobId: number) {
  qc.invalidateQueries({ queryKey: ["job", jobId] });
  for (const k of ["shortlist", "pipeline", "triage"]) {
    qc.invalidateQueries({ queryKey: [k] });
  }
}

export function useCheckH1BSponsorship(jobId: number) {
  const { launch } = useLaunchRun();
  return useMutation({
    mutationFn: () =>
      launch(
        "h1bSponsorship",
        () =>
          unwrap(
            api.POST("/api/jobs/{job_id}/h1b-sponsorship", {
              params: { path: { job_id: jobId } },
            }),
          ),
        // The check writes the *company-level* cache, which can change
        // sponsorship status shown for sibling jobs at the same employer on
        // every board — not just this job — so the board query keys stay
        // invalidated too (the launch default), unlike the single-job
        // scoped revise mutations below.
        undefined,
        { jobId },
      ),
  });
}

export function useSetStage(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (status: string) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { status },
        }),
      ),
    onSuccess: () => {
      invalidateBoards(qc, jobId);
      toast.success("Stage updated");
    },
    onError: () => toast.error("Failed to update stage"),
  });
}

export function useUpsertApplication(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { status: string; notes?: string | null }) =>
      unwrap(
        api.PUT("/api/jobs/{job_id}/application", {
          params: { path: { job_id: jobId } },
          body: vars,
        }),
      ),
    onSuccess: () => {
      invalidateBoards(qc, jobId);
      toast.success("Application saved");
    },
  });
}

export function useRenderVersion(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) =>
      unwrap(
        api.POST("/api/resume-versions/{version_id}/render", {
          params: { path: { version_id: versionId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}

export function useReviseVersion(jobId: number) {
  const { launch } = useLaunchRun();
  return useMutation({
    mutationFn: (vars: { versionId: number; instruction: string; reReview?: boolean }) => {
      const reReview = vars.reReview ?? false;
      return launch(
        "revise",
        () =>
          unwrap(
            api.POST("/api/resume-versions/{version_id}/revise", {
              params: { path: { version_id: vars.versionId } },
              body: { instruction: vars.instruction, reReview },
            }),
          ),
        ["job"],
        {
          versionId: vars.versionId,
          jobId,
          instruction: vars.instruction,
          reReview,
        },
      );
    },
  });
}

export function useSelectResume(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/select-resume/{version_id}", {
          params: { path: { job_id: jobId, version_id: versionId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}

export function useReviseCoverLetter(jobId: number) {
  const { launch } = useLaunchRun();
  return useMutation({
    mutationFn: (vars: { coverLetterId: number; instruction: string }) =>
      launch(
        "coverLetterRevise",
        () =>
          unwrap(
            api.POST("/api/cover-letters/{cover_letter_id}/revise", {
              params: { path: { cover_letter_id: vars.coverLetterId } },
              body: { instruction: vars.instruction, reReview: false },
            }),
          ),
        ["job"],
        { coverLetterId: vars.coverLetterId, jobId, instruction: vars.instruction },
      ),
  });
}

export function useSelectCoverLetter(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (coverLetterId: number) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/select-cover-letter/{cover_letter_id}", {
          params: { path: { job_id: jobId, cover_letter_id: coverLetterId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}
