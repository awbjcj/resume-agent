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

/**
 * Clearing the application's resume selection. This is not merely the inverse
 * of selecting: it is the only way past the delete gate, since the API refuses
 * to delete a version an application still points at.
 */
export function useDeselectResume(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/jobs/{job_id}/select-resume", {
          params: { path: { job_id: jobId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
    onError: () => toast.error("Failed to unselect"),
  });
}

export function useDeselectCoverLetter(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/jobs/{job_id}/select-cover-letter", {
          params: { path: { job_id: jobId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
    onError: () => toast.error("Failed to unselect"),
  });
}

/**
 * Deleting artifacts invalidates the boards, not just the job: a row's
 * reported version count and rendered state are read straight off these
 * tables, so a board left uninvalidated would keep showing artifacts that no
 * longer exist.
 *
 * The error toast carries the server's own message rather than a generic one,
 * because the two failure modes need different fixes from the user: an id
 * that is gone (reload) versus one that is in use (unselect it first).
 */
function useDeleteArtifacts<TVars>(
  jobId: number,
  mutationFn: (vars: TVars) => Promise<unknown>,
  successMessage: (vars: TVars) => string,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (_data, vars) => {
      invalidateBoards(qc, jobId);
      toast.success(successMessage(vars));
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDeleteVersions(jobId: number) {
  return useDeleteArtifacts(
    jobId,
    (ids: number[]) =>
      ids.length === 1
        ? unwrap(
            api.DELETE("/api/resume-versions/{version_id}", {
              params: { path: { version_id: ids[0] } },
            }),
          )
        : unwrap(api.POST("/api/resume-versions/bulk-delete", { body: { ids } })),
    deletedVersionsMessage,
  );
}

export function useDeleteCoverLetters(jobId: number) {
  return useDeleteArtifacts(
    jobId,
    (ids: number[]) =>
      ids.length === 1
        ? unwrap(
            api.DELETE("/api/cover-letters/{cover_letter_id}", {
              params: { path: { cover_letter_id: ids[0] } },
            }),
          )
        : unwrap(api.POST("/api/cover-letters/bulk-delete", { body: { ids } })),
    deletedCoverLettersMessage,
  );
}

const deletedVersionsMessage = (ids: number[]) =>
  `Deleted ${ids.length} version${ids.length === 1 ? "" : "s"}`;

const deletedCoverLettersMessage = (ids: number[]) =>
  `Deleted ${ids.length} cover letter${ids.length === 1 ? "" : "s"}`;

export function useGenerateCoverLetter(jobId: number) {
  const { launch } = useLaunchRun();
  return useMutation({
    mutationFn: () =>
      launch(
        "coverLetter",
        () =>
          unwrap(
            api.POST("/api/cover-letters", {
              body: { jobIds: [jobId], approved: false },
            }),
          ),
        // Same call the Pipeline bulk action makes, so it keeps the same board
        // invalidation: a new cover letter can change what a job's row reports.
        undefined,
        { jobId },
      ),
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
